import React from 'react';
import { CheckCircle2, History, Plus, RefreshCw, Settings2, Trash2, Users } from 'lucide-react';
import { apiFetch } from '../../../api/client';
import { CustomDatePicker, CustomDropdown, CustomSelect } from '../../../components/CustomInputs';
import ConfirmDialog from '../../../components/feedback/ConfirmDialog';
import NotificationToast from '../../../components/feedback/NotificationToast';
import { useConfirmDialog, usePopupToast } from '../../../components/feedback/hooks';
import { getApiErrorMessage, unwrapApiData } from '../../../types/api';
import type {
    Assistant,
    MonthlyCheckRule,
    MonthlySanctionSettings,
    SanctionOperation,
    WorkoffItem,
} from '../../../types/domain';
import { formatMskToLocal, getMskDateOffsetStr } from '../../../utils/datetime';

type SanctionKind = 'check' | 'point' | 'percent' | 'oral' | 'strict';
type RecipientMode = 'all_active' | 'live_without_active_session' | 'selected_only';
type WorkoffMetric = 'spec' | 'complaints' | 'mchat';
type TabId = 'issue' | 'history' | 'settings';

interface WorkoffDraftItem {
    local_id: string;
    metric: WorkoffMetric;
    multiplier: string;
    period_start: string;
    period_end: string;
}

const DEFAULT_SETTINGS: MonthlySanctionSettings = {
    check_cycle_size: 5,
    check_immunity_hours_per_day: 4,
    point_immunity_hours_per_day: 5,
    percent_immunity_hours_per_day: 6,
    check_relief_hours_per_day: 4,
    point_relief_hours_per_day: 5,
    percent_relief_hours_per_day: 6,
    check_relief_min_streak_days: 2,
    point_relief_min_streak_days: 2,
    percent_relief_min_streak_days: 2,
    percent_relief_step_amount: 3,
    daily_norm_spec: 4,
    daily_norm_complaints: 0,
    daily_norm_mchat: 0,
};

const DEFAULT_CHECK_RULES: MonthlyCheckRule[] = [
    { range_start: 1, range_end: 2, penalty_kind: 'point', penalty_amount: 1 },
    { range_start: 3, range_end: 3, penalty_kind: 'point', penalty_amount: 2 },
    { range_start: 4, range_end: 5, penalty_kind: 'percent', penalty_amount: 3 },
    { range_start: 6, range_end: 6, penalty_kind: 'percent', penalty_amount: 5 },
    { range_start: 7, range_end: 7, penalty_kind: 'oral', penalty_amount: 1 },
    { range_start: 8, range_end: null, penalty_kind: 'strict', penalty_amount: 1 },
];

const createWorkoffDraft = (metric: WorkoffMetric = 'spec'): WorkoffDraftItem => ({
    local_id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    metric,
    multiplier: '1',
    period_start: getMskDateOffsetStr(1),
    period_end: getMskDateOffsetStr(8),
});

const getAssistantDisplay = (assistant: Assistant) => `${assistant.nickname} · ${assistant.pr_id}`;

const mergeOperation = (next: SanctionOperation, existing?: SanctionOperation): SanctionOperation => {
    if (!existing) return next;
    return {
        ...existing,
        ...next,
        members: next.members ?? existing.members,
        workoff_items: next.workoff_items ?? existing.workoff_items,
    };
};

const isAssistantLiveInSpec = (assistant: Assistant) => assistant.status === 'assigned' || Boolean(assistant.assigned_to_type);

const seedAssistantIds = (assistants: Assistant[], mode: RecipientMode): string[] => {
    if (mode === 'selected_only') return [];
    if (mode === 'live_without_active_session') {
        return assistants.filter((assistant) => !isAssistantLiveInSpec(assistant)).map((assistant) => String(assistant.pr_id));
    }
    return assistants.map((assistant) => String(assistant.pr_id));
};

const buildWorkoffPayload = (items: WorkoffDraftItem[]): WorkoffItem[] => (
    items
        .map((item) => ({
            metric: item.metric,
            multiplier: Number(item.multiplier),
            period_start: item.period_start,
            period_end: item.period_end,
        }))
        .filter((item) => item.period_start && item.period_end && Number.isFinite(item.multiplier) && item.multiplier > 0)
);

const toAmountPayload = (kind: SanctionKind, raw: string) => {
    if (kind === 'check') return 1;
    if (kind === 'oral' || kind === 'strict') return undefined;
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
};

const kindLabel = (kind: SanctionKind) => ({
    check: 'Галка',
    point: 'Штрафные баллы',
    percent: 'Штрафной процент',
    oral: 'Устный',
    strict: 'Строгий',
}[kind]);

const recipientLabel = (mode: RecipientMode) => ({
    all_active: 'Всем',
    live_without_active_session: 'Всем, кто не в спеке',
    selected_only: 'Конкретным людям',
}[mode]);

const operationStatusLabel = (status: SanctionOperation['status']) => ({
    queued: 'В очереди выдачи',
    processing: 'Обрабатывается',
    completed: 'Исполнено',
    cancelled: 'Отменено',
    failed: 'Ошибка',
}[status]);

const processingModeLabel = (mode?: SanctionOperation['processing_mode'] | null) => {
    if (mode === 'manual_now') return 'Вручную сразу';
    if (mode === 'nightly_auto') return 'Автоматически после 00:00';
    return 'Еще не выдано';
};

const processedByLabel = (operation: SanctionOperation) => {
    if (operation.processed_by_name) return operation.processed_by_name;
    if (operation.processing_mode === 'nightly_auto') return 'Система';
    if (operation.processed_by_id) return operation.processed_by_id;
    return 'Не указано';
};

const issueStatusLabel = (status: 'pending' | 'issued' | 'skipped_immunity' | 'failed') => ({
    pending: 'Ожидает',
    issued: 'Выдано',
    skipped_immunity: 'Пропущен по иммунитету',
    failed: 'Ошибка',
}[status]);

const workoffMetricLabel = (metric: WorkoffMetric) => ({
    spec: 'Спек',
    complaints: 'Жалобы',
    mchat: 'MChat',
}[metric]);

const rangeUpperBound = (end: number | null) => (end === null ? Number.POSITIVE_INFINITY : end);

const rangeLabel = (start: number, end: number | null) => {
    if (end === null) return `${start}+`;
    return start === end ? String(start) : `${start}-${end}`;
};

const availableMetrics = (items: WorkoffDraftItem[], currentId?: string): WorkoffMetric[] => {
    const used = new Set(items.filter((item) => item.local_id !== currentId).map((item) => item.metric));
    return (['spec', 'complaints', 'mchat'] as WorkoffMetric[]).filter((metric) => !used.has(metric));
};

const firstAvailableMetric = (items: WorkoffDraftItem[]): WorkoffMetric | null => availableMetrics(items)[0] ?? null;

const findOverlapMessage = (rules: MonthlyCheckRule[]) => {
    const sorted = [...rules].sort(
        (left, right) => left.range_start - right.range_start || rangeUpperBound(left.range_end) - rangeUpperBound(right.range_end),
    );
    for (let index = 0; index < sorted.length - 1; index += 1) {
        const current = sorted[index];
        const next = sorted[index + 1];
        if (next.range_start <= rangeUpperBound(current.range_end)) {
            return `Диапазоны ${rangeLabel(current.range_start, current.range_end)} и ${rangeLabel(next.range_start, next.range_end)} пересекаются`;
        }
    }
    return null;
};

const isFixedAmountKind = (kind: SanctionKind) => kind === 'check' || kind === 'oral' || kind === 'strict';
const needsAutoReliefDate = (kind: SanctionKind) => kind === 'oral' || kind === 'strict';
const formatOperationQueuedAt = (operation: SanctionOperation) => formatMskToLocal(operation.queued_at ?? operation.created_at);
const normalizeCheckRule = (rule: MonthlyCheckRule): MonthlyCheckRule => ({
    ...rule,
    penalty_amount: isFixedAmountKind(rule.penalty_kind as SanctionKind) ? 1 : rule.penalty_amount,
});

const SanctionsQueueManagement = () => {
    const { toast, showToast, closeToast } = usePopupToast(3500);
    const { confirm, dialogProps } = useConfirmDialog();
    const [activeTab, setActiveTab] = React.useState<TabId>('issue');
    const [assistants, setAssistants] = React.useState<Assistant[]>([]);
    const [operations, setOperations] = React.useState<SanctionOperation[]>([]);
    const [selectedDraftId, setSelectedDraftId] = React.useState<string | null>(null);
    const [selectedHistoryId, setSelectedHistoryId] = React.useState<string | null>(null);
    const [settings, setSettings] = React.useState<MonthlySanctionSettings>(DEFAULT_SETTINGS);
    const [checkRules, setCheckRules] = React.useState<MonthlyCheckRule[]>(DEFAULT_CHECK_RULES);
    const [loading, setLoading] = React.useState(true);
    const [busy, setBusy] = React.useState(false);
    const [selectionDirty, setSelectionDirty] = React.useState(false);
    const [createAddAssistantId, setCreateAddAssistantId] = React.useState('');
    const [detailAddAssistantId, setDetailAddAssistantId] = React.useState('');

    const [operationForm, setOperationForm] = React.useState({
        penalty_kind: 'check' as SanctionKind,
        penalty_amount: '1',
        auto_relief_date: '',
        recipient_mode: 'live_without_active_session' as RecipientMode,
        selectedAssistantIds: [] as string[],
        workoffItems: [] as WorkoffDraftItem[],
    });

    const assistantOptions = React.useMemo(
        () => assistants.map((assistant) => ({ value: String(assistant.pr_id), label: getAssistantDisplay(assistant) })),
        [assistants],
    );

    const getAssistantLabel = React.useCallback((assistantId: string, nickname?: string | null) => {
        const assistant = assistants.find((item) => String(item.pr_id) === String(assistantId));
        if (assistant) return getAssistantDisplay(assistant);
        if (nickname) return `${nickname} · ${assistantId}`;
        return assistantId;
    }, [assistants]);

    const draftOperations = React.useMemo(
        () => operations.filter((item) => item.status === 'queued'),
        [operations],
    );

    const historyOperations = React.useMemo(
        () => operations.filter((item) => item.status === 'completed' || item.status === 'failed'),
        [operations],
    );

    const selectedDraft = React.useMemo(
        () => draftOperations.find((item) => String(item.id) === selectedDraftId) ?? null,
        [draftOperations, selectedDraftId],
    );

    const selectedHistory = React.useMemo(
        () => historyOperations.find((item) => String(item.id) === selectedHistoryId) ?? null,
        [historyOperations, selectedHistoryId],
    );

    const createAvailableAssistantOptions = React.useMemo(
        () => assistantOptions.filter((option) => !operationForm.selectedAssistantIds.includes(option.value)),
        [assistantOptions, operationForm.selectedAssistantIds],
    );

    const detailAvailableAssistantOptions = React.useMemo(() => {
        const selectedIds = new Set((selectedDraft?.members ?? []).map((member) => String(member.assistant_id)));
        return assistantOptions.filter((option) => !selectedIds.has(option.value));
    }, [assistantOptions, selectedDraft]);

    const ruleOverlapMessage = React.useMemo(() => findOverlapMessage(checkRules), [checkRules]);

    const currentCheckRules = React.useMemo(
        () => checkRules.map((rule) => normalizeCheckRule(rule)),
        [checkRules],
    );

    const loadAssistants = React.useCallback(async () => {
        const response = await apiFetch('/api/assistants');
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            throw new Error(getApiErrorMessage(payload, 'Не удалось загрузить ассистентов'));
        }
        const payload = await response.json() as unknown;
        const data = unwrapApiData<Assistant[]>(payload);
        setAssistants(Array.isArray(data) ? data : []);
    }, []);

    const loadOperations = React.useCallback(async () => {
        const response = await apiFetch('/api/sanction-operations');
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            throw new Error(getApiErrorMessage(payload, 'Не удалось загрузить операции выдачи'));
        }
        const payload = await response.json() as unknown;
        const data = unwrapApiData<SanctionOperation[]>(payload);
        setOperations((prev) => {
            const previousById = new Map(prev.map((item) => [String(item.id), item]));
            return (Array.isArray(data) ? data : [])
                .map((item) => mergeOperation(item, previousById.get(String(item.id))))
                .filter((item) => item.status !== 'cancelled');
        });
    }, []);

    const loadSettings = React.useCallback(async () => {
        const [settingsRes, rulesRes] = await Promise.all([
            apiFetch('/api/sanction-settings'),
            apiFetch('/api/sanction-settings/check-rules'),
        ]);
        if (!settingsRes.ok || !rulesRes.ok) {
            const payload = await (settingsRes.ok ? rulesRes : settingsRes).json().catch(() => ({}));
            throw new Error(getApiErrorMessage(payload, 'Не удалось загрузить настройки санкций'));
        }
        const settingsPayload = await settingsRes.json() as unknown;
        const rulesPayload = await rulesRes.json() as unknown;
        setSettings(unwrapApiData<MonthlySanctionSettings>(settingsPayload));
        const nextRules = unwrapApiData<MonthlyCheckRule[]>(rulesPayload);
        setCheckRules(Array.isArray(nextRules) ? nextRules : DEFAULT_CHECK_RULES);
    }, []);

    const fetchOperation = React.useCallback(async (operationId: string) => {
        const response = await apiFetch(`/api/sanction-operations/${operationId}`);
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            throw new Error(getApiErrorMessage(payload, 'Не удалось загрузить операцию'));
        }
        const payload = await response.json() as unknown;
        const data = unwrapApiData<SanctionOperation>(payload);
        setOperations((prev) => {
            const next = prev.slice();
            const index = next.findIndex((item) => String(item.id) === String(data.id));
            if (index >= 0) next[index] = mergeOperation(data, next[index]);
            else next.unshift(data);
            return next.filter((item) => item.status !== 'cancelled');
        });
    }, []);

    React.useEffect(() => {
        let cancelled = false;
        (async () => {
            setLoading(true);
            try {
                await Promise.all([loadAssistants(), loadOperations(), loadSettings()]);
            } catch (error) {
                if (!cancelled) {
                    showToast(error instanceof Error ? error.message : 'Не удалось загрузить раздел', 'error');
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [loadAssistants, loadOperations, loadSettings, showToast]);

    React.useEffect(() => {
        const intervalId = window.setInterval(() => {
            void (async () => {
                try {
                    await Promise.all([loadAssistants(), loadOperations()]);
                    if (selectedDraftId) {
                        await fetchOperation(selectedDraftId);
                    }
                    if (selectedHistoryId) {
                        await fetchOperation(selectedHistoryId);
                    }
                } catch (error) {
                    console.error('Failed to refresh sanctions view:', error);
                }
            })();
        }, 5000);
        return () => window.clearInterval(intervalId);
    }, [fetchOperation, loadAssistants, loadOperations, selectedDraftId, selectedHistoryId]);

    React.useEffect(() => {
        setSelectedDraftId((prev) => (prev && draftOperations.some((item) => String(item.id) === prev) ? prev : String(draftOperations[0]?.id ?? '')) || null);
    }, [draftOperations]);

    React.useEffect(() => {
        setSelectedHistoryId((prev) => (prev && historyOperations.some((item) => String(item.id) === prev) ? prev : String(historyOperations[0]?.id ?? '')) || null);
    }, [historyOperations]);

    React.useEffect(() => {
        if (!selectedDraftId) return;
        const operation = draftOperations.find((item) => String(item.id) === selectedDraftId);
        if (!operation || (operation.members !== undefined && operation.workoff_items !== undefined)) {
            return;
        }
        void fetchOperation(selectedDraftId).catch((error) => {
            console.error('Failed to load sanction operation details:', error);
        });
    }, [draftOperations, fetchOperation, selectedDraftId]);

    React.useEffect(() => {
        if (!selectedHistoryId) return;
        const operation = historyOperations.find((item) => String(item.id) === selectedHistoryId);
        if (!operation || (operation.members !== undefined && operation.workoff_items !== undefined)) {
            return;
        }
        void fetchOperation(selectedHistoryId).catch((error) => {
            console.error('Failed to load sanction operation history details:', error);
        });
    }, [fetchOperation, historyOperations, selectedHistoryId]);

    React.useEffect(() => {
        if (selectionDirty) return;
        setOperationForm((prev) => ({
            ...prev,
            selectedAssistantIds: seedAssistantIds(assistants, prev.recipient_mode),
        }));
    }, [assistants, selectionDirty]);

    const runMutation = React.useCallback(async (successMessage: string, action: () => Promise<void>) => {
        setBusy(true);
        try {
            await action();
            showToast(successMessage);
        } catch (error) {
            showToast(error instanceof Error ? error.message : 'Операция завершилась ошибкой', 'error');
        } finally {
            setBusy(false);
        }
        }, [showToast]);

    const handleRecipientModeChange = (mode: RecipientMode) => {
        setOperationForm((prev) => ({
            ...prev,
            recipient_mode: mode,
            selectedAssistantIds: seedAssistantIds(assistants, mode),
        }));
        setSelectionDirty(false);
        setCreateAddAssistantId('');
    };

    const submitOperation = async () => {
        const amount = toAmountPayload(operationForm.penalty_kind, operationForm.penalty_amount);
        const needsWarningDate = needsAutoReliefDate(operationForm.penalty_kind);
        if (needsWarningDate && !operationForm.auto_relief_date) {
            throw new Error('Для устного и строгого наказания укажи дату автоснятия');
        }
        if (!isFixedAmountKind(operationForm.penalty_kind) && !amount) {
            throw new Error('Укажи корректный размер наказания');
        }
        const response = await apiFetch('/api/sanction-operations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                penalty_kind: operationForm.penalty_kind,
                ...(amount ? { penalty_amount: amount } : {}),
                ...(needsWarningDate ? { auto_relief_date: operationForm.auto_relief_date } : {}),
                recipient_mode: operationForm.recipient_mode,
                assistant_ids: operationForm.selectedAssistantIds,
                workoff_items: buildWorkoffPayload(operationForm.workoffItems),
            }),
        });
        const payload = await response.json().catch(() => ({} as unknown));
        if (!response.ok) {
            throw new Error(getApiErrorMessage(payload, 'Не удалось создать операцию'));
        }
        const operation = unwrapApiData<SanctionOperation>(payload);
        setOperations((prev) => [operation, ...prev.filter((item) => String(item.id) !== String(operation.id))]);
        setSelectedDraftId(String(operation.id));
        setActiveTab('issue');
        setOperationForm({
            penalty_kind: 'check',
            penalty_amount: '1',
            auto_relief_date: '',
            recipient_mode: 'live_without_active_session',
            selectedAssistantIds: seedAssistantIds(assistants, 'live_without_active_session'),
            workoffItems: [],
        });
        setSelectionDirty(false);
        setCreateAddAssistantId('');
    };

    const saveSettings = async () => {
        if (checkRules.length === 0) {
            throw new Error('Нельзя сохранить пустой набор правил галок');
        }
        if (ruleOverlapMessage) {
            throw new Error(ruleOverlapMessage);
        }
        const [settingsResponse, rulesResponse] = await Promise.all([
            apiFetch('/api/sanction-settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings),
            }),
            apiFetch('/api/sanction-settings/check-rules', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    rules: currentCheckRules.map((rule) => ({
                        range_start: rule.range_start,
                        range_end: rule.range_end,
                        penalty_kind: rule.penalty_kind,
                        penalty_amount: isFixedAmountKind(rule.penalty_kind as SanctionKind) ? 1 : rule.penalty_amount,
                    })),
                }),
            }),
        ]);
        const settingsPayload = await settingsResponse.json().catch(() => ({} as unknown));
        const rulesPayload = await rulesResponse.json().catch(() => ({} as unknown));
        if (!settingsResponse.ok) {
            throw new Error(getApiErrorMessage(settingsPayload, 'Не удалось сохранить настройки'));
        }
        if (!rulesResponse.ok) {
            throw new Error(getApiErrorMessage(rulesPayload, 'Не удалось сохранить правила галок'));
        }
        setSettings(unwrapApiData<MonthlySanctionSettings>(settingsPayload));
        const savedRules = unwrapApiData<MonthlyCheckRule[]>(rulesPayload);
        setCheckRules(Array.isArray(savedRules) ? savedRules : []);
    };

    const issueOperationNow = async (operationId: string) => {
        const response = await apiFetch(`/api/sanction-operations/${operationId}/issue-now`, { method: 'POST' });
        const payload = await response.json().catch(() => ({} as unknown));
        if (!response.ok) {
            throw new Error(getApiErrorMessage(payload, 'Не удалось выполнить действие'));
        }
        await loadOperations();
    };

    const cancelOperation = async (operationId: string) => {
        const response = await apiFetch(`/api/sanction-operations/${operationId}/cancel`, { method: 'POST' });
        const payload = await response.json().catch(() => ({} as unknown));
        if (!response.ok) {
            throw new Error(getApiErrorMessage(payload, 'Не удалось выполнить действие'));
        }
        const operation = unwrapApiData<SanctionOperation>(payload);
        setOperations((prev) => prev.filter((item) => String(item.id) !== String(operation.id)));
        setSelectedDraftId((prev) => (prev === String(operation.id) ? null : prev));
    };

    const handleIssueNow = async (operationId: string) => {
        const confirmed = await confirm({
            title: 'Выдать санкцию сейчас?',
            message: 'Иммунитеты учитываться не будут. Санкция будет выдана всем ассистентам в списке.',
            confirmLabel: 'Выдать сейчас',
            cancelLabel: 'Отмена',
            tone: 'danger',
        });
        if (!confirmed) return;
        await runMutation(
            'Задача на выдачу отправлена в worker',
            () => issueOperationNow(operationId),
        );
    };

    const addOperationMember = async (operationId: string, assistantId: string) => {
        const response = await apiFetch(`/api/sanction-operations/${operationId}/members`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ assistant_id: assistantId }),
        });
        const payload = await response.json().catch(() => ({} as unknown));
        if (!response.ok) {
            throw new Error(getApiErrorMessage(payload, 'Не удалось добавить ассистента'));
        }
        await fetchOperation(operationId);
    };

    const removeOperationMember = async (operationId: string, assistantId: string) => {
        const response = await apiFetch(`/api/sanction-operations/${operationId}/members/${assistantId}`, {
            method: 'DELETE',
        });
        const payload = await response.json().catch(() => ({} as unknown));
        if (!response.ok) {
            throw new Error(getApiErrorMessage(payload, 'Не удалось удалить ассистента'));
        }
        await fetchOperation(operationId);
    };

    const addOperationWorkoff = () => {
        const nextMetric = firstAvailableMetric(operationForm.workoffItems);
        if (!nextMetric) return;
        setOperationForm((prev) => ({
            ...prev,
            workoffItems: [...prev.workoffItems, createWorkoffDraft(nextMetric)],
        }));
    };

    const addCheckRule = () => {
        const nextStart = checkRules.length === 0
            ? 1
            : Math.max(...checkRules.map((rule) => rule.range_end ?? rule.range_start)) + 1;
        setCheckRules((prev) => [
            ...prev,
            {
                range_start: nextStart,
                range_end: nextStart,
                penalty_kind: 'point',
                penalty_amount: 1,
            },
        ]);
    };

    const renderWorkoffItems = (
        items: WorkoffDraftItem[],
        onChange: (nextItems: WorkoffDraftItem[]) => void,
        readOnly = false,
    ) => {
        if (items.length === 0) {
            return (
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-5 text-center text-white/45">
                    Отработка не задана
                </div>
            );
        }

        return (
            <div className="space-y-3">
                {items.map((item) => {
                    const metricOptions = availableMetrics(items, item.local_id).concat(item.metric);
                    const uniqueMetricOptions = Array.from(new Set(metricOptions));
                    return (
                        <div key={item.local_id} className="rounded-xl border border-white/10 bg-black/20 p-4 grid grid-cols-1 md:grid-cols-4 gap-3">
                            <div>
                                <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">Тип</label>
                                <CustomDropdown
                                    value={item.metric}
                                    onChange={(value) => onChange(items.map((entry) => entry.local_id === item.local_id ? { ...entry, metric: value as WorkoffMetric } : entry))}
                                    options={uniqueMetricOptions.map((metric) => ({ value: metric, label: workoffMetricLabel(metric) }))}
                                    disabled={readOnly}
                                />
                            </div>
                            <div>
                                <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">X от нормы</label>
                                <input
                                    type="number"
                                    min="0"
                                    step="0.1"
                                    value={item.multiplier}
                                    onChange={(event) => onChange(items.map((entry) => entry.local_id === item.local_id ? { ...entry, multiplier: event.target.value } : entry))}
                                    disabled={readOnly}
                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
                                />
                            </div>
                            <div>
                                <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">Период с</label>
                                <CustomDatePicker
                                    value={item.period_start}
                                    onChange={(value) => onChange(items.map((entry) => entry.local_id === item.local_id ? { ...entry, period_start: value } : entry))}
                                />
                            </div>
                            <div className="flex flex-col gap-2">
                                <div>
                                    <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">Период по</label>
                                    <CustomDatePicker
                                        value={item.period_end}
                                        onChange={(value) => onChange(items.map((entry) => entry.local_id === item.local_id ? { ...entry, period_end: value } : entry))}
                                    />
                                </div>
                                {!readOnly && (
                                    <button
                                        type="button"
                                        onClick={() => onChange(items.filter((entry) => entry.local_id !== item.local_id))}
                                        className="self-end rounded-lg px-3 py-1.5 text-sm border border-rose-400/20 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20"
                                    >
                                        Удалить
                                    </button>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>
        );
    };

    const tabs = [
        { id: 'issue' as const, label: 'Выдача санкций', icon: <Users className="w-4 h-4" /> },
        { id: 'history' as const, label: 'История выдач', icon: <History className="w-4 h-4" /> },
        { id: 'settings' as const, label: 'Настройки санкций', icon: <Settings2 className="w-4 h-4" /> },
    ];

    if (loading) {
        return (
            <div className="rounded-2xl border border-white/10 bg-white/[0.04] px-6 py-10 text-center text-white/60">
                Загрузка раздела санкций...
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div className="flex gap-2 border-b border-white/10 pb-2">
                {tabs.map((tab) => (
                    <button
                        key={tab.id}
                        type="button"
                        onClick={() => setActiveTab(tab.id)}
                        className={`px-6 py-3 rounded-t-lg font-semibold transition-all relative flex items-center gap-2 ${activeTab === tab.id
                            ? 'bg-white/10 text-white border-b-2 border-blue-500'
                            : 'text-white/60 hover:text-white hover:bg-white/5'}`}
                    >
                        {tab.icon}
                        {tab.label}
                    </button>
                ))}
            </div>

            {activeTab === 'issue' && (
                <div className="space-y-6">
                    <section className="rounded-2xl border border-white/10 bg-white/[0.04] p-5 space-y-5">
                        <div className="flex items-center gap-3">
                            <Users className="w-5 h-5 text-sky-300" />
                            <h3 className="text-white font-semibold">Выдать общую санкцию</h3>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <div>
                                <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">Тип наказания</label>
                                <CustomDropdown
                                    value={operationForm.penalty_kind}
                                    onChange={(value) => setOperationForm((prev) => ({
                                        ...prev,
                                        penalty_kind: value as SanctionKind,
                                        penalty_amount: isFixedAmountKind(value as SanctionKind) ? '1' : prev.penalty_amount,
                                    }))}
                                    options={[
                                        { value: 'check', label: 'Галка' },
                                        { value: 'point', label: 'Штрафные баллы' },
                                        { value: 'percent', label: 'Штрафной процент' },
                                        { value: 'oral', label: 'Устный' },
                                        { value: 'strict', label: 'Строгий' },
                                    ]}
                                />
                            </div>
                            {!isFixedAmountKind(operationForm.penalty_kind) && (
                                <div>
                                    <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">Размер наказания</label>
                                    <input
                                        type="number"
                                        min="0"
                                        step="0.0001"
                                        value={operationForm.penalty_amount}
                                        onChange={(event) => setOperationForm((prev) => ({ ...prev, penalty_amount: event.target.value }))}
                                        className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
                                        placeholder="1"
                                    />
                                </div>
                            )}
                            {needsAutoReliefDate(operationForm.penalty_kind) && (
                                <div>
                                    <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">Дата автоснятия</label>
                                    <CustomDatePicker
                                        value={operationForm.auto_relief_date}
                                        onChange={(value) => setOperationForm((prev) => ({ ...prev, auto_relief_date: value }))}
                                    />
                                </div>
                            )}
                            <div>
                                <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">Кому выдать</label>
                                <CustomDropdown
                                    value={operationForm.recipient_mode}
                                    onChange={(value) => handleRecipientModeChange(value as RecipientMode)}
                                    options={[
                                        { value: 'all_active', label: 'Всем' },
                                        { value: 'live_without_active_session', label: 'Всем, кто не в спеке' },
                                        { value: 'selected_only', label: 'Конкретным людям' },
                                    ]}
                                />
                            </div>
                        </div>

                        <div className="space-y-3">
                            <div className="text-white font-medium">Список выбранных ассистентов</div>
                            {selectionDirty && (
                                <div className="rounded-xl border border-amber-400/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
                                    Список был изменен вручную. Автоматическое обновление по полю «Кому выдать» сейчас отключено.
                                    Чтобы снова включить его, заново выбери нужный режим в поле «Кому выдать».
                                </div>
                            )}
                            <div className="space-y-2">
                                {operationForm.selectedAssistantIds.length === 0 ? (
                                    <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-5 text-center text-white/45">
                                        Список пуст. Выбери режим или добавь ассистентов вручную.
                                    </div>
                                ) : operationForm.selectedAssistantIds.map((assistantId) => {
                                    const assistant = assistants.find((item) => String(item.pr_id) === assistantId);
                                    return (
                                        <div key={assistantId} className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 flex items-center justify-between gap-3">
                                            <div className="text-white/80">{assistant ? getAssistantDisplay(assistant) : assistantId}</div>
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    setSelectionDirty(true);
                                                    setOperationForm((prev) => ({
                                                        ...prev,
                                                        selectedAssistantIds: prev.selectedAssistantIds.filter((id) => id !== assistantId),
                                                    }));
                                                }}
                                                className="rounded-lg p-2 text-rose-200 hover:bg-rose-500/10"
                                            >
                                                <Trash2 className="w-4 h-4" />
                                            </button>
                                        </div>
                                    );
                                })}
                            </div>
                            <div className="flex flex-col md:flex-row gap-3">
                                <div className="flex-1">
                                    <CustomSelect
                                        value={createAddAssistantId}
                                        onChange={(value) => setCreateAddAssistantId(String(value))}
                                        options={createAvailableAssistantOptions}
                                        placeholder="Добавить ассистента"
                                    />
                                </div>
                                <button
                                    type="button"
                                    disabled={!createAddAssistantId}
                                    onClick={() => {
                                        setSelectionDirty(true);
                                        setOperationForm((prev) => ({
                                            ...prev,
                                            selectedAssistantIds: prev.selectedAssistantIds.includes(createAddAssistantId)
                                                ? prev.selectedAssistantIds
                                                : [...prev.selectedAssistantIds, createAddAssistantId],
                                        }));
                                        setCreateAddAssistantId('');
                                    }}
                                    className="rounded-lg px-4 py-2 text-sm font-medium bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50"
                                >
                                    <Plus className="w-4 h-4 inline-block mr-1" />
                                    Добавить ассистента
                                </button>
                            </div>
                        </div>

                        <div className="space-y-3">
                            <div className="flex items-center justify-between">
                                <div className="text-white font-medium">Отработка</div>
                                <button
                                    type="button"
                                    onClick={addOperationWorkoff}
                                    disabled={availableMetrics(operationForm.workoffItems).length === 0}
                                    className="rounded-lg px-3 py-1.5 text-sm border border-emerald-400/20 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
                                >
                                    + Добавить отработку
                                </button>
                            </div>
                            {renderWorkoffItems(operationForm.workoffItems, (nextItems) => setOperationForm((prev) => ({ ...prev, workoffItems: nextItems })))}
                        </div>

                        <button
                            disabled={busy}
                            onClick={() => runMutation('Операция добавлена в очередь выдачи', submitOperation)}
                            className="rounded-xl px-4 py-2 text-sm font-medium bg-sky-500/20 border border-sky-400/30 text-sky-100 hover:bg-sky-500/30 disabled:opacity-50"
                        >
                            Создать операцию
                        </button>
                    </section>

                    <section className="grid grid-cols-1 xl:grid-cols-[1fr_1.35fr] gap-6">
                        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-5 space-y-4">
                            <div className="flex items-center justify-between">
                                <h3 className="text-white font-semibold">Очередь выдачи</h3>
                                <button className="text-white/70 hover:text-white" onClick={() => runMutation('Список обновлен', loadOperations)}>
                                    <RefreshCw className={`w-4 h-4 ${busy ? 'animate-spin' : ''}`} />
                                </button>
                            </div>
                            <div className="space-y-3 max-h-[34rem] overflow-y-auto pr-1">
                                {draftOperations.length === 0 ? (
                                    <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-6 text-center text-white/45">
                                        Очередь выдачи пуста
                                    </div>
                                ) : draftOperations.map((operation) => {
                                    const active = String(operation.id) === selectedDraftId;
                                    return (
                                        <button
                                            key={operation.id}
                                            type="button"
                                            onClick={() => setSelectedDraftId(String(operation.id))}
                                            className={`w-full text-left rounded-2xl border px-4 py-3 transition ${active ? 'border-sky-400/40 bg-sky-500/10' : 'border-white/10 bg-black/20 hover:bg-white/[0.06]'}`}
                                        >
                                            <div className="flex items-center justify-between gap-4">
                                                <div>
                                                    <div className="text-white font-medium">#{operation.id} · {kindLabel(operation.penalty_kind)}</div>
                                                    <div className="text-white/50 text-sm">{recipientLabel(operation.recipient_mode)} · {formatOperationQueuedAt(operation)}</div>
                                                </div>
                                                <div className="text-right">
                                                    <div className="text-white/80 text-sm">{operation.effective_members ?? 0} участников</div>
                                                    <div className="text-white/40 text-xs">{operationStatusLabel(operation.status)}</div>
                                                </div>
                                            </div>
                                        </button>
                                    );
                                })}
                            </div>
                        </div>

                        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-5 space-y-4">
                            <div className="flex items-center justify-between">
                                <h3 className="text-white font-semibold">Состав операции</h3>
                                {selectedDraft && (
                                    <div className="flex gap-2">
                                        <button
                                            className="px-3 py-2 rounded-xl border border-amber-400/20 text-amber-200 hover:bg-amber-500/10"
                                            onClick={() => void handleIssueNow(String(selectedDraft.id))}
                                        >
                                            Выдать сейчас
                                        </button>
                                        <button
                                            className="px-3 py-2 rounded-xl border border-rose-400/20 text-rose-200 hover:bg-rose-500/10"
                                            onClick={() => runMutation('Операция отменена', () => cancelOperation(String(selectedDraft.id)))}
                                        >
                                            Отменить
                                        </button>
                                    </div>
                                )}
                            </div>
                            {!selectedDraft ? (
                                <div className="text-white/50">Выбери операцию из очереди слева</div>
                            ) : (
                                <>
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                                        <div className="rounded-xl bg-black/20 border border-white/10 p-3 text-white/70">Наказание<div className="text-white font-medium">{kindLabel(selectedDraft.penalty_kind)}{!isFixedAmountKind(selectedDraft.penalty_kind) ? ` · ${selectedDraft.penalty_amount}` : ''}</div></div>
                                        <div className="rounded-xl bg-black/20 border border-white/10 p-3 text-white/70">Кому выдать<div className="text-white font-medium">{recipientLabel(selectedDraft.recipient_mode)}</div></div>
                                        <div className="rounded-xl bg-black/20 border border-white/10 p-3 text-white/70">Статус<div className="text-white font-medium">{operationStatusLabel(selectedDraft.status)}</div></div>
                                        <div className="rounded-xl bg-black/20 border border-white/10 p-3 text-white/70">Участников<div className="text-white font-medium">{selectedDraft.effective_members ?? 0}</div></div>
                                        {selectedDraft.auto_relief_date && (
                                            <div className="rounded-xl bg-black/20 border border-white/10 p-3 text-white/70">Дата автоснятия<div className="text-white font-medium">{selectedDraft.auto_relief_date}</div></div>
                                        )}
                                    </div>

                                    {selectedDraft.workoff_items && selectedDraft.workoff_items.length > 0 && (
                                        <div className="space-y-2">
                                            <div className="text-white font-medium">Отработка</div>
                                            {selectedDraft.workoff_items.map((item, index) => (
                                                <div key={`${selectedDraft.id}-workoff-${index}`} className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-white/70">
                                                    {workoffMetricLabel(item.metric)} · x{item.multiplier} · {item.period_start} - {item.period_end}
                                                </div>
                                            ))}
                                        </div>
                                    )}

                                    <div className="space-y-3 rounded-xl border border-white/10 bg-black/20 p-4">
                                        <div className="text-white font-medium">Добавить ассистента</div>
                                        <div className="flex flex-col md:flex-row gap-3">
                                            <div className="flex-1">
                                                <CustomSelect
                                                    value={detailAddAssistantId}
                                                    onChange={(value) => setDetailAddAssistantId(String(value))}
                                                    options={detailAvailableAssistantOptions}
                                                    placeholder="Ассистент"
                                                />
                                            </div>
                                            <button
                                                disabled={!detailAddAssistantId}
                                                onClick={() => {
                                                    if ((selectedDraft.members ?? []).some((member) => String(member.assistant_id) === detailAddAssistantId)) {
                                                        showToast('Этот ассистент уже добавлен в выдачу', 'error');
                                                        return;
                                                    }
                                                    void runMutation('Ассистент добавлен в операцию', async () => {
                                                        await addOperationMember(String(selectedDraft.id), detailAddAssistantId);
                                                        setDetailAddAssistantId('');
                                                    });
                                                }}
                                                className="rounded-lg px-4 py-2 text-sm font-medium bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50"
                                            >
                                                <Plus className="w-4 h-4 inline-block mr-1" />
                                                Добавить
                                            </button>
                                        </div>
                                    </div>

                                    <div className="space-y-2 max-h-[28rem] overflow-y-auto pr-1">
                                        {(selectedDraft.members ?? []).map((member) => (
                                            <div key={`${member.operation_id}-${member.assistant_id}`} className="rounded-xl border border-white/10 bg-black/20 p-3 flex items-center justify-between gap-4">
                                                <div className="text-white font-medium">{getAssistantLabel(String(member.assistant_id), member.nickname)}</div>
                                                <button
                                                    onClick={() => runMutation('Ассистент удален из операции', () => removeOperationMember(String(selectedDraft.id), String(member.assistant_id)))}
                                                    className="rounded-lg p-2 text-rose-200 hover:bg-rose-500/10"
                                                >
                                                    <Trash2 className="w-4 h-4" />
                                                </button>
                                            </div>
                                        ))}
                                    </div>
                                </>
                            )}
                        </div>
                    </section>
                </div>
            )}

            {activeTab === 'history' && (
                <section className="grid grid-cols-1 xl:grid-cols-[1fr_1.35fr] gap-6">
                    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-5 space-y-4">
                        <div className="flex items-center justify-between">
                            <h3 className="text-white font-semibold">История выдач</h3>
                            <button className="text-white/70 hover:text-white" onClick={() => runMutation('Список обновлен', loadOperations)}>
                                <RefreshCw className={`w-4 h-4 ${busy ? 'animate-spin' : ''}`} />
                            </button>
                        </div>
                        <div className="space-y-3 max-h-[34rem] overflow-y-auto pr-1">
                            {historyOperations.length === 0 ? (
                                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-6 text-center text-white/45">
                                    История выдач пуста
                                </div>
                            ) : historyOperations.map((operation) => {
                                const active = String(operation.id) === selectedHistoryId;
                                return (
                                    <button
                                        key={operation.id}
                                        type="button"
                                        onClick={() => setSelectedHistoryId(String(operation.id))}
                                        className={`w-full text-left rounded-2xl border px-4 py-3 transition ${active ? 'border-sky-400/40 bg-sky-500/10' : 'border-white/10 bg-black/20 hover:bg-white/[0.06]'}`}
                                    >
                                        <div className="flex items-center justify-between gap-4">
                                            <div>
                                                <div className="text-white font-medium">#{operation.id} · {kindLabel(operation.penalty_kind)}</div>
                                                <div className="text-white/50 text-sm">{recipientLabel(operation.recipient_mode)} · {formatOperationQueuedAt(operation)}</div>
                                                <div className="text-white/40 text-xs">{processingModeLabel(operation.processing_mode)} · {processedByLabel(operation)}</div>
                                            </div>
                                            <div className="text-right">
                                                <div className="text-white/80 text-sm">{operationStatusLabel(operation.status)}</div>
                                                <div className="text-white/40 text-xs">{operation.issued_members ?? 0}/{operation.effective_members ?? 0}</div>
                                            </div>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-5 space-y-4">
                        <div className="flex items-center gap-3">
                            <History className="w-5 h-5 text-sky-300" />
                            <h3 className="text-white font-semibold">Детали выдачи</h3>
                        </div>
                        {!selectedHistory ? (
                            <div className="text-white/50">Выбери операцию слева</div>
                        ) : (
                            <>
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                                    <div className="rounded-xl bg-black/20 border border-white/10 p-3 text-white/70">Наказание<div className="text-white font-medium">{kindLabel(selectedHistory.penalty_kind)}{!isFixedAmountKind(selectedHistory.penalty_kind) ? ` · ${selectedHistory.penalty_amount}` : ''}</div></div>
                                    <div className="rounded-xl bg-black/20 border border-white/10 p-3 text-white/70">Кому выдавали<div className="text-white font-medium">{recipientLabel(selectedHistory.recipient_mode)}</div></div>
                                    <div className="rounded-xl bg-black/20 border border-white/10 p-3 text-white/70">Дата постановки в очередь<div className="text-white font-medium">{formatOperationQueuedAt(selectedHistory)}</div></div>
                                    <div className="rounded-xl bg-black/20 border border-white/10 p-3 text-white/70">Статус<div className="text-white font-medium">{operationStatusLabel(selectedHistory.status)}</div></div>
                                    <div className="rounded-xl bg-black/20 border border-white/10 p-3 text-white/70">Как выдано<div className="text-white font-medium">{processingModeLabel(selectedHistory.processing_mode)}</div></div>
                                    <div className="rounded-xl bg-black/20 border border-white/10 p-3 text-white/70">Кем выдано<div className="text-white font-medium">{processedByLabel(selectedHistory)}</div></div>
                                    {selectedHistory.auto_relief_date && (
                                        <div className="rounded-xl bg-black/20 border border-white/10 p-3 text-white/70">Дата автоснятия<div className="text-white font-medium">{selectedHistory.auto_relief_date}</div></div>
                                    )}
                                </div>

                                {selectedHistory.workoff_items && selectedHistory.workoff_items.length > 0 && (
                                    <div className="space-y-2">
                                        <div className="text-white font-medium">Отработка</div>
                                        {selectedHistory.workoff_items.map((item, index) => (
                                            <div key={`${selectedHistory.id}-history-workoff-${index}`} className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-white/70">
                                                {workoffMetricLabel(item.metric)} · x{item.multiplier} · {item.period_start} - {item.period_end}
                                            </div>
                                        ))}
                                    </div>
                                )}

                                <div className="space-y-2 max-h-[28rem] overflow-y-auto pr-1">
                                    {(selectedHistory.members ?? []).map((member) => (
                                        <div key={`${member.operation_id}-${member.assistant_id}`} className="rounded-xl border border-white/10 bg-black/20 p-3 space-y-1">
                                            <div className="flex items-center justify-between gap-4">
                                                <div className="text-white font-medium">{getAssistantLabel(String(member.assistant_id), member.nickname)}</div>
                                                <div className="text-sm text-white/65">{issueStatusLabel(member.issue_status)}</div>
                                            </div>
                                            {member.issue_reason && (
                                                <div className="text-xs text-white/45">{member.issue_reason}</div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </>
                        )}
                    </div>
                </section>
            )}

            {activeTab === 'settings' && (
                <section className="rounded-2xl border border-white/10 bg-white/[0.04] p-5 space-y-5">
                    <div className="flex items-center gap-3">
                        <CheckCircle2 className="w-5 h-5 text-emerald-300" />
                        <h3 className="text-white font-semibold">Настройки санкций</h3>
                    </div>

                    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                        <div className="rounded-2xl border border-white/10 bg-black/20 p-4 space-y-3">
                            <div className="text-white font-medium">Размер полного набора галок</div>
                            <input
                                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-white"
                                value={settings.check_cycle_size}
                                onChange={(event) => setSettings((prev) => ({ ...prev, check_cycle_size: Number(event.target.value) }))}
                            />
                        </div>

                        <div className="rounded-2xl border border-white/10 bg-black/20 p-4 space-y-3">
                            <div className="text-white font-medium">Иммунитеты</div>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                {[
                                    ['check_immunity_hours_per_day', 'Галка'],
                                    ['point_immunity_hours_per_day', 'Штрафные баллы'],
                                    ['percent_immunity_hours_per_day', 'Штрафной процент'],
                                ].map(([field, label]) => (
                                    <div key={field}>
                                        <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">{label}</label>
                                        <input
                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-white"
                                            value={String((settings as unknown as Record<string, string | number>)[field] ?? '')}
                                            onChange={(event) => setSettings((prev) => ({ ...prev, [field]: Number(event.target.value) }))}
                                        />
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div className="rounded-2xl border border-white/10 bg-black/20 p-4 space-y-3">
                            <div className="text-white font-medium">Снятие галок</div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                {[
                                    ['check_relief_hours_per_day', 'Часы за день'],
                                    ['check_relief_min_streak_days', 'Дней подряд'],
                                ].map(([field, label]) => (
                                    <div key={field}>
                                        <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">{label}</label>
                                        <input
                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-white"
                                            value={String((settings as unknown as Record<string, string | number>)[field] ?? '')}
                                            onChange={(event) => setSettings((prev) => ({ ...prev, [field]: Number(event.target.value) }))}
                                        />
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div className="rounded-2xl border border-white/10 bg-black/20 p-4 space-y-3">
                            <div className="text-white font-medium">Снятие штрафных баллов</div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                {[
                                    ['point_relief_hours_per_day', 'Часы за день'],
                                    ['point_relief_min_streak_days', 'Дней подряд'],
                                ].map(([field, label]) => (
                                    <div key={field}>
                                        <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">{label}</label>
                                        <input
                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-white"
                                            value={String((settings as unknown as Record<string, string | number>)[field] ?? '')}
                                            onChange={(event) => setSettings((prev) => ({ ...prev, [field]: Number(event.target.value) }))}
                                        />
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div className="rounded-2xl border border-white/10 bg-black/20 p-4 space-y-3">
                            <div className="text-white font-medium">Снятие штрафного процента</div>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                {[
                                    ['percent_relief_hours_per_day', 'Часы за день'],
                                    ['percent_relief_min_streak_days', 'Дней подряд'],
                                    ['percent_relief_step_amount', 'Шаг снятия'],
                                ].map(([field, label]) => (
                                    <div key={field}>
                                        <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">{label}</label>
                                        <input
                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-white"
                                            value={String((settings as unknown as Record<string, string | number>)[field] ?? '')}
                                            onChange={(event) => setSettings((prev) => ({ ...prev, [field]: Number(event.target.value) }))}
                                        />
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div className="rounded-2xl border border-white/10 bg-black/20 p-4 space-y-3">
                            <div className="text-white font-medium">Нормы для отработки</div>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                {[
                                    ['daily_norm_spec', 'Спек'],
                                    ['daily_norm_complaints', 'Жалобы'],
                                    ['daily_norm_mchat', 'MChat'],
                                ].map(([field, label]) => (
                                    <div key={field}>
                                        <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">{label}</label>
                                        <input
                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-white"
                                            value={String((settings as unknown as Record<string, string | number>)[field] ?? '')}
                                            onChange={(event) => setSettings((prev) => ({ ...prev, [field]: Number(event.target.value) }))}
                                        />
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    <div className="space-y-3">
                        <div className="flex items-center justify-between">
                            <div className="text-white font-medium">Правила галок</div>
                            <button
                                type="button"
                                onClick={addCheckRule}
                                className="rounded-lg px-3 py-1.5 text-sm border border-white/10 text-white/80 hover:bg-white/[0.06]"
                            >
                                + Добавить правило
                            </button>
                        </div>
                        {ruleOverlapMessage && (
                            <div className="rounded-xl border border-rose-400/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
                                {ruleOverlapMessage}
                            </div>
                        )}
                        <div className="space-y-3">
                            {checkRules.map((rule, index) => (
                                <div key={`${rule.range_start}-${rule.range_end ?? 'plus'}-${index}`} className="rounded-2xl border border-white/10 bg-black/20 p-4 space-y-3">
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="text-white/70">Наборы галок: {rangeLabel(rule.range_start, rule.range_end)}</div>
                                        <button
                                            type="button"
                                            onClick={() => setCheckRules((prev) => prev.filter((_, currentIndex) => currentIndex !== index))}
                                            className="rounded-lg p-2 text-rose-200 hover:bg-rose-500/10"
                                        >
                                            <Trash2 className="w-4 h-4" />
                                        </button>
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                                        <div>
                                            <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">От</label>
                                            <input
                                                type="number"
                                                min="1"
                                                value={rule.range_start}
                                                onChange={(event) => setCheckRules((prev) => prev.map((item, itemIndex) => itemIndex === index ? { ...item, range_start: Number(event.target.value) } : item))}
                                                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-white"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">До</label>
                                            <div className="space-y-2">
                                                <input
                                                    type="number"
                                                    min="1"
                                                    disabled={rule.range_end === null}
                                                    value={rule.range_end ?? ''}
                                                    placeholder={rule.range_end === null ? 'Без верхней границы' : ''}
                                                    onChange={(event) => setCheckRules((prev) => prev.map((item, itemIndex) => itemIndex === index ? { ...item, range_end: Number(event.target.value) } : item))}
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-white disabled:opacity-50"
                                                />
                                                <label className="flex items-center gap-2 text-sm text-white/60">
                                                    <input
                                                        type="checkbox"
                                                        checked={rule.range_end === null}
                                                        onChange={(event) => setCheckRules((prev) => prev.map((item, itemIndex) => {
                                                            if (itemIndex !== index) return item;
                                                            return {
                                                                ...item,
                                                                range_end: event.target.checked ? null : item.range_start,
                                                            };
                                                        }))}
                                                        className="rounded border-white/20 bg-black/30"
                                                    />
                                                    И далее
                                                </label>
                                            </div>
                                        </div>
                                        <div>
                                            <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">Наказание</label>
                                            <CustomDropdown
                                                value={rule.penalty_kind}
                                                onChange={(value) => setCheckRules((prev) => prev.map((item, itemIndex) => itemIndex === index ? {
                                                    ...item,
                                                    penalty_kind: value as MonthlyCheckRule['penalty_kind'],
                                                    penalty_amount: isFixedAmountKind(value as SanctionKind) ? 1 : item.penalty_amount,
                                                } : item))}
                                                options={[
                                                    { value: 'point', label: 'Штрафные баллы' },
                                                    { value: 'percent', label: 'Штрафной процент' },
                                                    { value: 'oral', label: 'Устный' },
                                                    { value: 'strict', label: 'Строгий' },
                                                ]}
                                            />
                                        </div>
                                        {!isFixedAmountKind(rule.penalty_kind as SanctionKind) && (
                                            <div>
                                                <label className="text-xs text-white/45 uppercase tracking-wide mb-1 block">Размер</label>
                                                <input
                                                    type="number"
                                                    min="0"
                                                    step="0.0001"
                                                    value={rule.penalty_amount}
                                                    onChange={(event) => setCheckRules((prev) => prev.map((item, itemIndex) => itemIndex === index ? { ...item, penalty_amount: Number(event.target.value) } : item))}
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-white"
                                                />
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    <button
                        className="px-4 py-2 rounded-xl bg-emerald-500/20 border border-emerald-400/30 text-emerald-100 hover:bg-emerald-500/30 disabled:opacity-50"
                        disabled={busy}
                        onClick={() => runMutation('Настройки санкций сохранены', saveSettings)}
                    >
                        Сохранить настройки
                    </button>
                </section>
            )}

            <ConfirmDialog {...dialogProps} />

            {toast && (
                <NotificationToast
                    message={toast.message}
                    type={toast.type}
                    onClose={closeToast}
                />
            )}
        </div>
    );
};

export default SanctionsQueueManagement;
