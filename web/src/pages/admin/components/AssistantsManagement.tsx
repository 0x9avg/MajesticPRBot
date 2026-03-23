import React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Check, Clipboard, Coins, RefreshCw, Timer, Trash2, Wrench } from 'lucide-react';

import { CustomDatePicker, CustomDropdown, CustomSelect, CustomTimePicker } from '../../../components/CustomInputs';
import ConfirmDialog from '../../../components/feedback/ConfirmDialog';
import NotificationToast from '../../../components/feedback/NotificationToast';
import { useConfirmDialog, usePopupToast } from '../../../components/feedback/hooks';
import { apiFetch } from '../../../api/client';
import type { KnownRole, UserContext } from '../../../types/auth';
import { unwrapApiData } from '../../../types/api';
import type {
    ActiveSanction,
    AssistantSessionRecord,
    AssistantSessionTargetEvent,
    AssistantSessionTargetStreamer,
    WorkoffPreviewAssistant,
    WorkoffPreviewResponse,
    WorkoffProgressDay,
} from '../../../types/domain';
import { parseMskDate, getMskDateOffsetStr, getMskNow, formatMskToLocal, formatToMskIso } from '../../../utils/datetime';
import { ROLE_LABELS } from '../../../utils/roles';
import {
    useAssistantDayStatus,
    useAssistantDetail,
    useAssistantsList,
    useAssistantSanctions,
    useAssistantSessions,
    useSessionTargets,
} from './assistants/hooks';

void React;

interface AssistantsManagementProps {
    user?: UserContext | null;
}

type UserWithManageableRoles = UserContext & {
    manageable_roles?: KnownRole[];
};

interface SelectOption {
    value: string;
    label: string;
}

type SanctionKind = 'check' | 'point' | 'percent' | 'oral' | 'strict';
type WorkoffMetric = 'spec' | 'complaints' | 'mchat';
type MutationMethod = 'POST' | 'PATCH' | 'PUT' | 'DELETE';

interface WorkoffDraftItem {
    local_id: string;
    metric: WorkoffMetric;
    multiplier: string;
    period_start: string;
    period_end: string;
}

const workoffMetricLabel = (metric: WorkoffMetric) => ({
    spec: 'Спек',
    complaints: 'Жалобы',
    mchat: 'MChat',
}[metric]);

const workoffStatusLabel = (status?: string | null) => ({
    pending: 'В процессе',
    completed: 'Завершена',
    failed: 'Не выполнена',
    leave_skipped: 'Пропуск по У/О',
}[status || ''] || status || 'Неизвестно');

const workoffDayStatusLabel = (status?: string | null) => ({
    pending: 'Ожидает',
    completed: 'выполнена',
    failed: 'не выполнена',
    leave_skipped: 'У/О',
}[status || ''] || status || 'Неизвестно');

const workoffCountedLabel = (countsForWorkoff?: boolean) => (countsForWorkoff ? 'учтен' : 'не учтен');

const workoffManualStatusLabel = (manualStatus?: string | null) => ({
    P: 'вручную: П',
    U: 'вручную: У',
    O: 'вручную: О',
}[manualStatus || ''] || (manualStatus ? `вручную: ${manualStatus}` : ''));

const workoffPreviewItemKey = (assistantId: string, metric: WorkoffMetric, index: number) =>
    `${assistantId}-${metric}-${index}`;

const workoffDayStatusTone = (status?: string | null) => {
    if (status === 'completed') return 'text-emerald-200 bg-emerald-500/10 border-emerald-400/20';
    if (status === 'failed') return 'text-rose-200 bg-rose-500/10 border-rose-400/20';
    if (status === 'leave_skipped') return 'text-amber-200 bg-amber-500/10 border-amber-400/20';
    return 'text-sky-200 bg-sky-500/10 border-sky-400/20';
};

const formatDateTime = (value?: string | null) => formatMskToLocal(value);

const formatMetricValue = (value?: number | null, fractionDigits = 2) => {
    const numeric = Number(value ?? 0);
    if (!Number.isFinite(numeric)) return '0';
    return numeric
        .toFixed(fractionDigits)
        .replace(/(\.\d*?[1-9])0+$/, '$1')
        .replace(/\.0+$/, '')
        .replace(/\.00$/, '');
};

const formatWorkoffCounter = (value?: number | null) => Number(value ?? 0);

const toNumberOrUndefined = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return undefined;
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : undefined;
};

const toLocalDateTimeInput = (isoValue?: string | null) => {
    const dt = parseMskDate(isoValue);
    if (!dt) return '';
    return formatToMskIso(dt).substring(0, 16);
};

const splitDateTime = (combined: string) => {
    const [date = '', time = ''] = combined.split('T');
    return { date, time };
};

const mergeDateTimePart = (current: string, part: 'date' | 'time', value: string) => {
    const { date, time } = splitDateTime(current);
    if (part === 'date') return value ? `${value}T${time || '00:00'}` : '';
    return date ? `${date}T${value || '00:00'}` : '';
};

const parseLocalDateTimeToIso = (localValue: string) => {
    if (!localValue) return null;
    return localValue.length === 16 ? `${localValue}:00` : localValue;
};

const getDefaultManualWindow = () => {
    const end = getMskNow();
    end.setSeconds(0, 0);
    const start = new Date(end.getTime() - 60 * 60 * 1000);
    return {
        started_at: formatToMskIso(start).substring(0, 16),
        ended_at: formatToMskIso(end).substring(0, 16),
    };
};

const createInitialManualSanctionForm = () => ({
    kind: 'point' as SanctionKind,
    amount: '1',
    auto_relief_date: '',
    workoffItems: [] as WorkoffDraftItem[],
});

const createInitialManualSessionForm = () => {
    const manualWindow = getDefaultManualWindow();
    return {
        target_type: 'streamer',
        target_id: '',
        target_name: '',
        started_at: manualWindow.started_at,
        ended_at: manualWindow.ended_at,
        is_probation: false,
        priority: '0',
    };
};

const createInitialSessionEditState = () => ({
    target_type: 'streamer',
    target_id: '',
    target_name: '',
    started_at: '',
    ended_at: '',
    priority_override: '',
    is_probation: false,
});

const makeStreamerOption = (streamer: AssistantSessionTargetStreamer): SelectOption => {
    const status = streamer.is_online ? 'онлайн' : 'оффлайн';
    return {
        value: String(streamer.streamer_id),
        label: `${streamer.streamer_name} · ID ${streamer.streamer_id} · ${status}`,
    };
};

const makeEventOption = (event: AssistantSessionTargetEvent): SelectOption => {
    const status = event.is_active ? 'активно' : 'неактивно';
    return {
        value: String(event.id),
        label: `${event.name} · ID ${event.id} · ${status}`,
    };
};

const createEmptyWorkoffDraft = (): WorkoffDraftItem => ({
    local_id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    metric: 'spec',
    multiplier: '1',
    period_start: getMskDateOffsetStr(1),
    period_end: getMskDateOffsetStr(8),
});

const getAvailableWorkoffMetrics = (items: WorkoffDraftItem[], currentId?: string): WorkoffMetric[] => {
    const used = new Set(items.filter((item) => item.local_id !== currentId).map((item) => item.metric));
    return (['spec', 'complaints', 'mchat'] as WorkoffMetric[]).filter((metric) => !used.has(metric));
};

const normalizeWorkoffPreviewResponse = (payload: unknown): WorkoffPreviewAssistant[] => {
    const data = unwrapApiData<
        WorkoffPreviewResponse
        | WorkoffPreviewAssistant[]
        | { assistants?: WorkoffPreviewAssistant[]; items?: WorkoffPreviewAssistant[] }
    >(payload);
    if (Array.isArray(data)) return data;
    if (data && typeof data === 'object') {
        if (Array.isArray(data.assistants)) return data.assistants;
        if (Array.isArray(data.items)) return data.items;
    }
    return [];
};

const getSourceTypeLabel = (value?: string | null) => {
    switch (value) {
        case 'manual':
            return 'Ручная';
        case 'queued_batch':
            return 'Общая санкция';
        case 'check_cycle':
            return 'Правило галок';
        case 'legacy_migration':
            return 'Миграция';
        default:
            return value || 'Неизвестно';
    }
};

const ensureOptionExists = (
    options: SelectOption[],
    value?: string,
    prefix = 'ID',
): SelectOption[] => {
    if (!value) return options;
    if (options.some((option) => option.value === value)) return options;
    return [{ value, label: `${prefix} ${value} (не найден)` }, ...options];
};

const getTargetDisplayName = (session: AssistantSessionRecord) => {
    if (session.target_type === 'manual') {
        return session.target_name || 'manual';
    }
    return session.target_name || (session.target_id != null ? String(session.target_id) : '—');
};

const getRoleLabel = (role?: string | null) => {
    if (!role) return 'Не указана';
    return ROLE_LABELS[role as keyof typeof ROLE_LABELS] ?? role;
};

const WorkoffDaysList = ({ days, keyPrefix }: { days: WorkoffProgressDay[]; keyPrefix: string }) => (
    <div className="space-y-2">
        {days.map((day, index) => (
            <div
                key={`${keyPrefix}-${day.date}-${index}`}
                className="flex flex-col gap-2 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-white/70 md:flex-row md:items-center md:justify-between"
            >
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-white/90">{day.date}</span>
                    <span className={`rounded-full border px-2 py-0.5 ${workoffDayStatusTone(day.day_status)}`}>
                        {workoffDayStatusLabel(day.day_status)}
                    </span>
                    {day.manual_status && (
                        <span className="text-white/45">{workoffManualStatusLabel(day.manual_status)}</span>
                    )}
                </div>
                <div className="flex flex-wrap gap-3 text-white/50">
                    <span>Требуется: {formatMetricValue(day.required_amount ?? 0)}</span>
                    <span>Отработано: {formatMetricValue(day.actual_amount ?? 0)}</span>
                    <span>{workoffCountedLabel(day.counts_for_workoff)}</span>
                </div>
            </div>
        ))}
    </div>
);

const InlineState = ({
    message,
    tone = 'neutral',
}: {
    message: string;
    tone?: 'neutral' | 'warning' | 'danger';
}) => {
    const className = {
        neutral: 'border-white/10 bg-white/[0.03] text-white/55',
        warning: 'border-yellow-500/20 bg-yellow-500/10 text-yellow-100',
        danger: 'border-rose-500/20 bg-rose-500/10 text-rose-100',
    }[tone];

    return (
        <div className={`rounded-xl border px-4 py-3 text-sm ${className}`}>
            {message}
        </div>
    );
};

const AssistantsManagement = ({ user = null }: AssistantsManagementProps) => {
    const { toast, showToast, closeToast } = usePopupToast(3000);
    const { confirm, dialogProps } = useConfirmDialog();

    const permissions = user?.permissions ?? {};
    const canManageSessions = permissions['assistants.sessions.manage'] === true;
    const canViewSessions = permissions['assistants.sessions.view'] === true || canManageSessions;
    const canManagePoints = permissions['assistants.points.update'] === true;
    const canManageSanctions = permissions['assistants.sanctions.manage'] === true;
    const canWarningsManage = permissions['assistants.warnings.manage'] === true;
    const canChangeRole = permissions['admin.users.role.update'] === true;
    const canDeactivateAssistant = permissions['admin.users.deactivate'] === true;
    const manageableRoles = ((user as UserWithManageableRoles | null)?.manageable_roles ?? []).filter(Boolean) as KnownRole[];
    const canViewAssistantData = (
        permissions['assistants.view'] === true
        || canViewSessions
        || canManagePoints
        || canManageSanctions
        || canWarningsManage
        || canChangeRole
        || canDeactivateAssistant
    );
    const hasAssistantsAccess = canViewAssistantData;

    const { assistants, loading: assistantsLoading, error: assistantsError, reload: reloadAssistants } = useAssistantsList(canViewAssistantData);
    const [selectedPrId, setSelectedPrId] = useState<string | null>(null);
    const { assistant: selectedAssistant, loading: assistantLoading, error: assistantError, reload: reloadAssistantDetail } = useAssistantDetail(selectedPrId, canViewAssistantData);
    const { sessions, loading: sessionsLoading, error: sessionsError, reload: reloadSessions } = useAssistantSessions(selectedPrId, canViewSessions);
    const { sanctions: activeSanctions, loading: sanctionsLoading, error: sanctionsError, reload: reloadSanctions } = useAssistantSanctions(selectedPrId, canViewAssistantData);
    const [dayStatusDate, setDayStatusDate] = useState(getMskDateOffsetStr(0));
    const { dayStatus: selectedDayStatus, loading: dayStatusLoading, error: dayStatusError, reload: reloadDayStatus } = useAssistantDayStatus(selectedPrId, dayStatusDate, canViewAssistantData);
    const { data: sessionTargets, loading: optionsLoading, error: optionsError, ensureLoaded: ensureSessionTargetsLoaded, reset: resetSessionTargets } = useSessionTargets(canManageSessions);
    const selectedIsSelf = Boolean(selectedAssistant && user?.discord_id != null)
        && String(selectedAssistant?.pr_id) === String(user?.discord_id);
    const canManageSelectedAssistant = React.useMemo(
        () => selectedIsSelf || (Boolean(selectedAssistant?.role) && manageableRoles.includes(selectedAssistant?.role as KnownRole)),
        [manageableRoles, selectedAssistant?.role, selectedIsSelf],
    );
    const canEditSelectedAssistant = canChangeRole && canManageSelectedAssistant;
    const canDeactivateSelectedAssistant = canDeactivateAssistant && canManageSelectedAssistant;
    const targetIsReadOnly = Boolean(selectedAssistant)
        && !canManageSelectedAssistant
        && (canManageSessions || canManagePoints || canManageSanctions || canWarningsManage || canChangeRole || canDeactivateAssistant);
    const targetReadOnlyMessage = targetIsReadOnly
        ? 'Эта учетная запись выше вашего уровня и доступна только для просмотра.'
        : null;

    const [copiedId, setCopiedId] = useState(false);
    const [search, setSearch] = useState('');
    const [busy, setBusy] = useState(false);
    const [editingSessionId, setEditingSessionId] = useState<number | null>(null);
    const [sessionEdit, setSessionEdit] = useState(createInitialSessionEditState);
    const [pointsForm, setPointsForm] = useState({ adjustmentChange: '' });
    const [mchatForm, setMchatForm] = useState({ count: '' });
    const [manualSanctionForm, setManualSanctionForm] = useState(createInitialManualSanctionForm);
    const [manualWorkoffPreview, setManualWorkoffPreview] = useState<WorkoffPreviewAssistant[]>([]);
    const [manualWorkoffPreviewLoading, setManualWorkoffPreviewLoading] = useState(false);
    const [manualWorkoffPreviewError, setManualWorkoffPreviewError] = useState<string | null>(null);
    const [manualWorkoffPreviewExpanded, setManualWorkoffPreviewExpanded] = useState<Record<string, boolean>>({});
    const [manualReliefAmountBySanctionId, setManualReliefAmountBySanctionId] = useState<Record<string, string>>({});
    const [manualSessionForm, setManualSessionForm] = useState(createInitialManualSessionForm);
    const workoffPreviewRequestIdRef = useRef(0);

    useEffect(() => {
        if (!canManageSessions || !canManageSelectedAssistant) {
            resetSessionTargets();
            setEditingSessionId(null);
        }
    }, [canManageSelectedAssistant, canManageSessions, resetSessionTargets]);

    useEffect(() => {
        setCopiedId(false);
        setEditingSessionId(null);
        setSessionEdit(createInitialSessionEditState());
        setPointsForm({ adjustmentChange: '' });
        setMchatForm({ count: '' });
        setManualReliefAmountBySanctionId({});
    }, [selectedPrId]);

    useEffect(() => {
        if (!canViewAssistantData) {
            setSelectedPrId(null);
            return;
        }
        if (assistants.length === 0) {
            setSelectedPrId(null);
            return;
        }
        setSelectedPrId((current) => {
            if (current && assistants.some((assistant) => String(assistant.pr_id) === current)) {
                return current;
            }
            return String(assistants[0].pr_id);
        });
    }, [assistants, canViewAssistantData]);

    useEffect(() => {
        if (!canManageSessions || !canManageSelectedAssistant) return;
        const needsTargets = manualSessionForm.target_type !== 'manual'
            || (editingSessionId !== null && sessionEdit.target_type !== 'manual');
        if (!needsTargets) return;
        void ensureSessionTargetsLoaded();
    }, [canManageSelectedAssistant, canManageSessions, editingSessionId, ensureSessionTargetsLoaded, manualSessionForm.target_type, sessionEdit.target_type]);

    const filteredAssistants = useMemo(() => {
        const query = search.trim().toLowerCase();
        if (!query) return assistants;
        return assistants.filter((assistant) => (
            assistant.nickname.toLowerCase().includes(query)
            || String(assistant.pr_id).includes(query)
        ));
    }, [assistants, search]);

    const sanctionTotals = useMemo(() => (
        activeSanctions.reduce(
            (acc, sanction) => {
                const amount = Number(sanction.active_amount ?? 0);
                if (sanction.kind in acc) {
                    acc[sanction.kind as keyof typeof acc] += amount;
                }
                return acc;
            },
            { check: 0, point: 0, percent: 0, oral: 0, strict: 0 },
        )
    ), [activeSanctions]);

    const manualWorkoffItemsPayload = useMemo(() => {
        const seen = new Set<WorkoffMetric>();
        return manualSanctionForm.workoffItems
            .map((item) => ({
                metric: item.metric,
                multiplier: Number(item.multiplier),
                period_start: item.period_start,
                period_end: item.period_end,
            }))
            .filter((item) => (
                item.period_start
                && item.period_end
                && Number.isFinite(item.multiplier)
                && item.multiplier > 0
                && (seen.has(item.metric) ? false : (seen.add(item.metric), true))
            ));
    }, [manualSanctionForm.workoffItems]);

    const streamerOptions = useMemo(() => (sessionTargets?.streamers ?? []).map(makeStreamerOption), [sessionTargets?.streamers]);
    const eventOptions = useMemo(() => (sessionTargets?.events ?? []).map(makeEventOption), [sessionTargets?.events]);
    const streamerNameById = useMemo(() => Object.fromEntries((sessionTargets?.streamers ?? []).map((streamer) => [String(streamer.streamer_id), streamer.streamer_name])), [sessionTargets?.streamers]);
    const eventNameById = useMemo(() => Object.fromEntries((sessionTargets?.events ?? []).map((event) => [String(event.id), event.name])), [sessionTargets?.events]);
    const streamerPriorityById = useMemo(() => Object.fromEntries((sessionTargets?.streamers ?? []).map((streamer) => [String(streamer.streamer_id), streamer.priority ?? 0])), [sessionTargets?.streamers]);
    const eventPriorityById = useMemo(() => Object.fromEntries((sessionTargets?.events ?? []).map((event) => [String(event.id), event.priority ?? 0])), [sessionTargets?.events]);

    const manualTargetOptions = useMemo(() => {
        const baseOptions = manualSessionForm.target_type === 'event' ? eventOptions : streamerOptions;
        const prefix = manualSessionForm.target_type === 'event' ? 'Событие ID' : 'Стример ID';
        return ensureOptionExists(baseOptions, manualSessionForm.target_id || undefined, prefix);
    }, [eventOptions, manualSessionForm.target_id, manualSessionForm.target_type, streamerOptions]);

    const editTargetOptions = useMemo(() => {
        const baseOptions = sessionEdit.target_type === 'event' ? eventOptions : streamerOptions;
        const prefix = sessionEdit.target_type === 'event' ? 'Событие ID' : 'Стример ID';
        return ensureOptionExists(baseOptions, sessionEdit.target_id || undefined, prefix);
    }, [eventOptions, sessionEdit.target_id, sessionEdit.target_type, streamerOptions]);

    const roleOptions = useMemo(() => {
        const roles = new Set<KnownRole>(manageableRoles);
        if (selectedIsSelf && selectedAssistant?.role) {
            roles.add(selectedAssistant.role as KnownRole);
        }
        return Array.from(roles).map((role) => ({
            value: role,
            label: getRoleLabel(role),
        }));
    }, [manageableRoles, selectedAssistant?.role, selectedIsSelf]);

    const handleCopyId = () => {
        if (!selectedPrId || !navigator.clipboard) return;
        navigator.clipboard.writeText(selectedPrId)
            .then(() => {
                setCopiedId(true);
                window.setTimeout(() => setCopiedId(false), 1500);
                showToast('PR ID скопирован');
            })
            .catch(() => {
                showToast('Не удалось скопировать PR ID', 'error');
            });
    };

    const refreshSelectionData = useCallback(async () => {
        const tasks: Promise<unknown>[] = [];
        if (canViewAssistantData) {
            tasks.push(reloadAssistantDetail(), reloadSanctions(), reloadDayStatus());
        }
        if (canViewSessions) {
            tasks.push(reloadSessions());
        }
        if (tasks.length > 0) {
            await Promise.allSettled(tasks);
        }
    }, [canViewAssistantData, canViewSessions, reloadAssistantDetail, reloadDayStatus, reloadSanctions, reloadSessions]);

    const refreshDetailAndDayStatus = useCallback(async () => {
        await Promise.allSettled([reloadAssistantDetail(), reloadDayStatus()]);
    }, [reloadAssistantDetail, reloadDayStatus]);

    const refreshSanctionsAndDayStatus = useCallback(async () => {
        await Promise.allSettled([reloadAssistantDetail(), reloadSanctions(), reloadDayStatus()]);
    }, [reloadAssistantDetail, reloadDayStatus, reloadSanctions]);

    const refreshSessionsAndDayStatus = useCallback(async () => {
        await Promise.allSettled([reloadAssistantDetail(), reloadSessions(), reloadDayStatus()]);
    }, [reloadAssistantDetail, reloadDayStatus, reloadSessions]);

    const refreshListAndDetail = useCallback(async () => {
        await Promise.allSettled([reloadAssistants(), reloadAssistantDetail()]);
    }, [reloadAssistantDetail, reloadAssistants]);

    const runMutation = useCallback(async (
        endpoint: string,
        method: MutationMethod,
        payload: Record<string, unknown> | undefined,
        successMessage: string,
        afterSuccess?: () => Promise<void>,
    ) => {
        setBusy(true);
        try {
            const response = await apiFetch(endpoint, {
                method,
                headers: payload ? { 'Content-Type': 'application/json' } : undefined,
                body: payload ? JSON.stringify(payload) : undefined,
            });
            const json = await response.json().catch(() => ({} as unknown));
            if (!response.ok) {
                throw new Error((json as { detail?: string }).detail || 'Операция не выполнена');
            }
            if (afterSuccess) {
                await afterSuccess();
            }
            showToast(successMessage);
            return true;
        } catch (error: unknown) {
            showToast(error instanceof Error ? error.message : 'Операция не выполнена', 'error');
            return false;
        } finally {
            setBusy(false);
        }
    }, [showToast]);

    useEffect(() => {
        if (!selectedPrId || !canManageSanctions || !canManageSelectedAssistant || manualWorkoffItemsPayload.length === 0) {
            workoffPreviewRequestIdRef.current += 1;
            setManualWorkoffPreview([]);
            setManualWorkoffPreviewError(null);
            setManualWorkoffPreviewLoading(false);
            setManualWorkoffPreviewExpanded({});
            return;
        }

        const requestId = workoffPreviewRequestIdRef.current + 1;
        workoffPreviewRequestIdRef.current = requestId;
        setManualWorkoffPreviewLoading(true);
        setManualWorkoffPreviewError(null);

        const timerId = window.setTimeout(() => {
            void (async () => {
                try {
                    const response = await apiFetch('/api/sanctions/workoff-preview', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            assistant_ids: [selectedPrId],
                            workoff_items: manualWorkoffItemsPayload,
                        }),
                    });
                    const payload = await response.json().catch(() => ({} as unknown));
                    if (!response.ok) {
                        throw new Error((payload as { detail?: string }).detail || 'Не удалось загрузить предпросмотр отработки');
                    }
                    if (workoffPreviewRequestIdRef.current !== requestId) return;
                    setManualWorkoffPreview(normalizeWorkoffPreviewResponse(payload));
                    setManualWorkoffPreviewExpanded({});
                } catch (error: unknown) {
                    if (workoffPreviewRequestIdRef.current !== requestId) return;
                    setManualWorkoffPreview([]);
                    setManualWorkoffPreviewExpanded({});
                    setManualWorkoffPreviewError(error instanceof Error ? error.message : 'Не удалось загрузить предпросмотр отработки');
                } finally {
                    if (workoffPreviewRequestIdRef.current === requestId) {
                        setManualWorkoffPreviewLoading(false);
                    }
                }
            })();
        }, 250);

        return () => {
            window.clearTimeout(timerId);
        };
    }, [canManageSanctions, canManageSelectedAssistant, manualWorkoffItemsPayload, selectedPrId]);

    const ensureTargetsReady = useCallback(async (targetType: string) => {
        if (targetType === 'manual') return true;
        const loadedTargets = await ensureSessionTargetsLoaded();
        if (!loadedTargets) {
            showToast(optionsError || 'Справочник целей для сессий недоступен', 'error');
            return false;
        }
        const hasOptions = targetType === 'event'
            ? loadedTargets.events.length > 0
            : loadedTargets.streamers.length > 0;
        if (!hasOptions) {
            showToast(targetType === 'event' ? 'Нет доступных событий' : 'Нет доступных стримеров', 'error');
            return false;
        }
        return true;
    }, [ensureSessionTargetsLoaded, optionsError, showToast]);

    const handleManualSanctionCreate = async () => {
        if (!selectedPrId || !canManageSanctions || !canManageSelectedAssistant) return;
        const fixedAmountKind = ['check', 'oral', 'strict'].includes(manualSanctionForm.kind);
        const needsWarningDate = ['oral', 'strict'].includes(manualSanctionForm.kind);
        if (needsWarningDate && !manualSanctionForm.auto_relief_date) {
            showToast('Укажите дату автоснятия для устного или строгого наказания', 'error');
            return;
        }
        const needsAmount = !fixedAmountKind;
        const amount = needsAmount ? toNumberOrUndefined(manualSanctionForm.amount) : undefined;
        if (needsAmount && (!amount || amount <= 0)) {
            showToast('Укажите корректный размер санкции', 'error');
            return;
        }
        const success = await runMutation(
            '/api/assistant-sanctions',
            'POST',
            {
                assistant_id: selectedPrId,
                kind: manualSanctionForm.kind,
                ...(needsAmount ? { amount } : {}),
                ...(needsWarningDate ? { auto_relief_date: manualSanctionForm.auto_relief_date } : {}),
                workoff_items: manualWorkoffItemsPayload,
            },
            'Санкция выдана',
            refreshSanctionsAndDayStatus,
        );
        if (success) {
            setManualSanctionForm(createInitialManualSanctionForm());
            setManualWorkoffPreview([]);
            setManualWorkoffPreviewExpanded({});
            setManualWorkoffPreviewError(null);
        }
    };

    const handleManualRelief = async (sanction: ActiveSanction) => {
        if (!canManageSanctions || !canManageSelectedAssistant) return;
        const rawAmount = manualReliefAmountBySanctionId[sanction.sanction_id] ?? '';
        const amount = ['check', 'oral', 'strict'].includes(sanction.kind)
            ? 1
            : toNumberOrUndefined(rawAmount);
        if (!amount || amount <= 0) {
            showToast('Укажите корректный размер снятия', 'error');
            return;
        }
        const success = await runMutation(
            `/api/assistant-sanctions/${sanction.sanction_id}/reliefs`,
            'POST',
            {
                amount,
                relief_type: 'manual',
            },
            'Снятие сохранено',
            refreshSanctionsAndDayStatus,
        );
        if (success) {
            setManualReliefAmountBySanctionId((current) => {
                const next = { ...current };
                delete next[sanction.sanction_id];
                return next;
            });
        }
    };

    const handlePointsAdjust = async () => {
        if (!selectedPrId || !canManagePoints || !canManageSelectedAssistant) return;
        const adjustmentChange = toNumberOrUndefined(pointsForm.adjustmentChange);
        if (adjustmentChange === undefined || adjustmentChange === 0) {
            showToast('Укажите, на сколько изменить корректировку баллов', 'error');
            return;
        }
        const success = await runMutation(
            '/api/assistant-day-points',
            'POST',
            {
                assistant_id: selectedPrId,
                work_date: dayStatusDate,
                delta_points: Number((Number(selectedDayStatus?.manual_points_delta ?? 0) + adjustmentChange).toFixed(4)),
            },
            'Корректировка баллов сохранена',
            refreshDetailAndDayStatus,
        );
        if (success) {
            setPointsForm({ adjustmentChange: '' });
        }
    };

    const handleMchatSave = async () => {
        if (!selectedPrId || !canManagePoints || !canManageSelectedAssistant) return;
        const trimmed = mchatForm.count.trim();
        if (!trimmed) {
            showToast('Укажите количество MChat за день', 'error');
            return;
        }
        const parsed = Number(trimmed);
        if (!Number.isInteger(parsed) || parsed < 0) {
            showToast('Количество MChat должно быть целым числом от 0', 'error');
            return;
        }
        const success = await runMutation(
            '/api/assistant-day-mchat',
            'PUT',
            {
                assistant_id: selectedPrId,
                work_date: dayStatusDate,
                mchat_count: parsed,
            },
            'MChat за день сохранен',
            refreshDetailAndDayStatus,
        );
        if (success) {
            setMchatForm({ count: '' });
        }
    };

    const handleManualSessionCreate = async () => {
        if (!selectedPrId || !canManageSessions || !canManageSelectedAssistant) return;
        const startedAtIso = parseLocalDateTimeToIso(manualSessionForm.started_at);
        const endedAtIso = parseLocalDateTimeToIso(manualSessionForm.ended_at);
        if (!startedAtIso || !endedAtIso) {
            showToast('Укажите корректные начало и конец сессии', 'error');
            return;
        }
        if (new Date(endedAtIso).getTime() <= new Date(startedAtIso).getTime()) {
            showToast('Конец сессии должен быть позже начала', 'error');
            return;
        }
        if (!(await ensureTargetsReady(manualSessionForm.target_type))) {
            return;
        }
        if (manualSessionForm.target_type !== 'manual' && !manualSessionForm.target_id.trim()) {
            showToast('Выберите цель спека', 'error');
            return;
        }
        const parsedTargetId = toNumberOrUndefined(manualSessionForm.target_id);
        if (manualSessionForm.target_type !== 'manual' && parsedTargetId === undefined) {
            showToast('Некорректная цель спека', 'error');
            return;
        }
        const targetName = parsedTargetId !== undefined
            ? (
                manualSessionForm.target_type === 'event'
                    ? eventNameById[String(parsedTargetId)]
                    : streamerNameById[String(parsedTargetId)]
            ) || null
            : null;

        const success = await runMutation(
            `/api/assistants/${selectedPrId}/session`,
            'POST',
            {
                target_type: manualSessionForm.target_type,
                target_id: manualSessionForm.target_type === 'manual' ? null : parsedTargetId,
                target_name: manualSessionForm.target_type === 'manual'
                    ? (manualSessionForm.target_name.trim() || null)
                    : targetName,
                started_at: startedAtIso,
                ended_at: endedAtIso,
                is_probation: manualSessionForm.is_probation,
                priority: Number(manualSessionForm.priority || '0'),
            },
            'Ручная сессия добавлена',
            refreshSessionsAndDayStatus,
        );
        if (success) {
            setManualSessionForm(createInitialManualSessionForm());
        }
    };

    const handleSessionPatch = async (sessionId: number) => {
        if (!selectedPrId || !canManageSessions || !canManageSelectedAssistant) return;
        const startedAtIso = parseLocalDateTimeToIso(sessionEdit.started_at);
        const endedAtIso = parseLocalDateTimeToIso(sessionEdit.ended_at);
        if (!startedAtIso || !endedAtIso) {
            showToast('Укажите корректные начало и конец сессии', 'error');
            return;
        }
        if (new Date(endedAtIso).getTime() <= new Date(startedAtIso).getTime()) {
            showToast('Конец сессии должен быть позже начала', 'error');
            return;
        }
        if (!(await ensureTargetsReady(sessionEdit.target_type))) {
            return;
        }
        if (sessionEdit.target_type !== 'manual' && !sessionEdit.target_id.trim()) {
            showToast('Выберите цель спека', 'error');
            return;
        }
        const parsedTargetId = toNumberOrUndefined(sessionEdit.target_id);
        if (sessionEdit.target_type !== 'manual' && parsedTargetId === undefined) {
            showToast('Некорректная цель спека', 'error');
            return;
        }

        const defaultPriority = sessionEdit.target_type === 'event'
            ? eventPriorityById[String(parsedTargetId)] ?? 0
            : sessionEdit.target_type === 'streamer'
                ? streamerPriorityById[String(parsedTargetId)] ?? 0
                : 0;
        const targetName = parsedTargetId !== undefined
            ? (
                sessionEdit.target_type === 'event'
                    ? eventNameById[String(parsedTargetId)]
                    : streamerNameById[String(parsedTargetId)]
            ) || null
            : null;
        const payload: Record<string, unknown> = {
            target_type: sessionEdit.target_type,
            target_id: sessionEdit.target_type === 'manual' ? null : parsedTargetId,
            target_name: sessionEdit.target_type === 'manual'
                ? (sessionEdit.target_name.trim() || null)
                : targetName,
            started_at: startedAtIso,
            ended_at: endedAtIso,
            is_probation: sessionEdit.is_probation,
            priority_override: null,
        };
        if (sessionEdit.priority_override.trim() !== '') {
            const parsedOverride = Number(sessionEdit.priority_override);
            if (!Number.isFinite(parsedOverride)) {
                showToast('Некорректный приоритет', 'error');
                return;
            }
            payload.priority_override = parsedOverride === defaultPriority ? null : parsedOverride;
        }
        const success = await runMutation(
            `/api/assistants/${selectedPrId}/sessions/${sessionId}`,
            'PATCH',
            payload,
            'Сессия обновлена',
            refreshSessionsAndDayStatus,
        );
        if (success) {
            setEditingSessionId(null);
            setSessionEdit(createInitialSessionEditState());
        }
    };

    const handleSessionDelete = async (sessionId: number) => {
        if (!selectedPrId || !canManageSessions || !canManageSelectedAssistant) return;
        await runMutation(
            `/api/assistants/${selectedPrId}/sessions/${sessionId}`,
            'DELETE',
            undefined,
            'Сессия удалена',
            refreshSessionsAndDayStatus,
        );
    };

    const handleRoleChange = async (newRole: string) => {
        if (!selectedPrId || !selectedAssistant || !canEditSelectedAssistant || newRole === selectedAssistant.role) return;
        await runMutation(
            `/api/admin/users/${selectedPrId}/role`,
            'PATCH',
            {
                role: newRole,
            },
            `Роль изменена на ${getRoleLabel(newRole)}`,
            refreshListAndDetail,
        );
    };

    const handleDeactivateAssistant = async () => {
        if (!selectedPrId || !selectedAssistant || !canDeactivateSelectedAssistant) return;
        const confirmed = await confirm({
            title: 'Деактивировать учетную запись?',
            message: <>Учетная запись <span className="font-semibold text-white">{selectedAssistant.nickname}</span> будет деактивирована.</>,
            confirmLabel: 'Деактивировать',
            tone: 'danger',
        });
        if (!confirmed) return;

        const success = await runMutation(
            `/api/admin/users/${selectedPrId}/deactivate`,
            'POST',
            {},
            'Учетная запись деактивирована',
            async () => {
                setSelectedPrId(null);
                setEditingSessionId(null);
                await reloadAssistants();
            },
        );
        if (success) {
            setSessionEdit(createInitialSessionEditState());
        }
    };

    const beginEditingSession = async (session: AssistantSessionRecord) => {
        if (!canManageSessions || !canManageSelectedAssistant) return;
        if (session.target_type !== 'manual') {
            const ready = await ensureTargetsReady(session.target_type || 'streamer');
            if (!ready) return;
        }
        setEditingSessionId(session.id);
        setSessionEdit({
            target_type: session.target_type || 'streamer',
            target_id: session.target_id != null ? String(session.target_id) : '',
            target_name: session.target_name || '',
            started_at: toLocalDateTimeInput(session.started_at),
            ended_at: toLocalDateTimeInput(session.ended_at),
            priority_override: session.priority_override != null
                ? String(session.priority_override)
                : session.priority_auto != null
                    ? String(session.priority_auto)
                    : '',
            is_probation: Boolean(session.is_probation),
        });
    };

    const canShowRoleSection = canViewAssistantData;
    const selectionLoading = assistantLoading || (canViewAssistantData && !selectedAssistant && Boolean(selectedPrId));

    return (
        <div className="space-y-6 animate-[fadeIn_0.3s_ease-in-out]">
            <div className="flex items-center gap-4 border-b border-white/10 pb-6">
                <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-indigo-500/30 bg-indigo-500/20 text-indigo-400">
                    <Wrench className="h-6 w-6" />
                </div>
                <div>
                    <h2 className="text-2xl font-bold text-white">Ассистенты</h2>
                    <p className="text-white/60">Управление баллами, санкциями, ролями и сессиями</p>
                </div>
            </div>

            {!hasAssistantsAccess && (
                <InlineState message="Раздел недоступен для вашей роли." tone="warning" />
            )}

            {hasAssistantsAccess && !canViewAssistantData && (
                <InlineState message="Данные ассистентов недоступны для вашей роли." tone="warning" />
            )}

            {canViewAssistantData && assistantsError && (
                <InlineState message={assistantsError} tone="danger" />
            )}

            {hasAssistantsAccess && (
                <div className="space-y-4">
                    <div className="space-y-3 rounded-2xl border border-white/5 bg-black/20 p-4">
                        <input
                            type="text"
                            value={search}
                            onChange={(event) => setSearch(event.target.value)}
                            placeholder="Поиск: ник или PR ID"
                            className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white placeholder:text-white/30 transition-colors focus:border-white/20 focus:outline-none"
                        />
                        <div className="flex flex-wrap gap-2">
                            {!canViewAssistantData ? (
                                <div className="py-1 text-sm text-white/40">Список ассистентов недоступен</div>
                            ) : assistantsLoading ? (
                                <div className="py-1 text-sm text-white/50">Загрузка...</div>
                            ) : filteredAssistants.length === 0 ? (
                                <div className="py-1 text-sm text-white/40">Ничего не найдено</div>
                            ) : (
                                filteredAssistants.map((assistant) => (
                                    <button
                                        key={assistant.pr_id}
                                        type="button"
                                        onClick={() => setSelectedPrId(String(assistant.pr_id))}
                                        className={`shrink-0 rounded-xl border px-3 py-2 text-left text-sm transition-all ${
                                            String(assistant.pr_id) === selectedPrId
                                                ? 'border-indigo-400/40 bg-indigo-500/10 text-indigo-200 shadow-[0_0_10px_rgba(99,102,241,0.15)]'
                                                : 'border-white/10 bg-white/5 text-white/70 hover:border-white/20 hover:bg-white/10 hover:text-white/90'
                                        }`}
                                    >
                                        <div className="font-medium">{assistant.nickname}</div>
                                        <div className="text-xs text-white/40">PR {assistant.pr_id}</div>
                                    </button>
                                ))
                            )}
                        </div>
                    </div>

                    {!canViewAssistantData ? null : !selectedPrId ? (
                        <div className="rounded-2xl border border-white/5 bg-black/20 p-8 text-center text-white/50">
                            Выберите ассистента для управления
                        </div>
                    ) : selectionLoading ? (
                        <div className="rounded-2xl border border-white/5 bg-black/20 p-8 text-center text-white/50">
                            Загрузка данных ассистента...
                        </div>
                    ) : assistantError ? (
                        <InlineState message={assistantError} tone="danger" />
                    ) : !selectedAssistant ? (
                        <div className="rounded-2xl border border-white/5 bg-black/20 p-8 text-center text-white/50">
                            Профиль ассистента недоступен
                        </div>
                    ) : (
                        <>
                            <div className="grid grid-cols-1 gap-3 rounded-2xl border border-white/5 bg-black/20 p-4 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
                                <div className="rounded-xl bg-white/5 p-3">
                                    <div className="text-xs text-white/50">Ник</div>
                                    <div className="flex items-center gap-2">
                                        <div className="font-semibold text-white">{selectedAssistant.nickname}</div>
                                        <button
                                            type="button"
                                            onClick={handleCopyId}
                                            title={`Скопировать PR ID: ${selectedPrId}`}
                                            className="ml-auto rounded-lg p-1 text-white/30 transition-all hover:bg-white/10 hover:text-white/80"
                                        >
                                            {copiedId
                                                ? <Check className="h-3.5 w-3.5 text-green-400" />
                                                : <Clipboard className="h-3.5 w-3.5" />}
                                        </button>
                                    </div>
                                    <div className="mt-1 text-xs text-white/40">PR {selectedPrId}</div>
                                </div>
                                <div className="rounded-xl bg-white/5 p-3">
                                    <div className="text-xs text-white/50">Роль</div>
                                    <div className="font-semibold text-white">{getRoleLabel(selectedAssistant.role)}</div>
                                </div>
                                <div className="rounded-xl bg-white/5 p-3">
                                    <div className="text-xs text-white/50">Баллы до санкций</div>
                                    <div className="font-semibold text-green-300">{formatMetricValue(selectedAssistant.gross_points ?? 0)}</div>
                                </div>
                                <div className="rounded-xl bg-white/5 p-3">
                                    <div className="text-xs text-white/50">Баллы после санкций</div>
                                    <div className="font-semibold text-emerald-200">
                                        {formatMetricValue(selectedAssistant.net_points ?? selectedAssistant.gross_points ?? 0)}
                                    </div>
                                </div>
                                <div className="rounded-xl bg-white/5 p-3">
                                    <div className="text-xs text-white/50">Активные штрафные баллы</div>
                                    <div className="font-semibold text-amber-300">{formatMetricValue(sanctionTotals.point)}</div>
                                </div>
                                <div className="rounded-xl bg-white/5 p-3">
                                    <div className="text-xs text-white/50">Активный штраф, %</div>
                                    <div className="font-semibold text-amber-300">{formatMetricValue(sanctionTotals.percent)}%</div>
                                </div>
                                <div className="rounded-xl bg-white/5 p-3">
                                    <div className="text-xs text-white/50">Галки / устный / строгий</div>
                                    <div className="font-semibold text-white">
                                        {formatMetricValue(sanctionTotals.check)} / {formatMetricValue(sanctionTotals.oral)} / {formatMetricValue(sanctionTotals.strict)}
                                    </div>
                                </div>
                            </div>

                            {targetReadOnlyMessage && (
                                <InlineState message={targetReadOnlyMessage} tone="warning" />
                            )}

                            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                                <div className="space-y-3 rounded-2xl border border-white/5 bg-black/20 p-4">
                                    <div className="flex items-center gap-2 font-semibold text-white">
                                        <Coins className="h-4 w-4 text-green-400" />
                                        Баллы
                                    </div>
                                    {dayStatusError && (
                                        <InlineState message={dayStatusError} tone="danger" />
                                    )}
                                    <div className="grid grid-cols-1 gap-3 md:grid-cols-[180px_minmax(0,1fr)]">
                                        <div>
                                            <label className="mb-1 block text-xs text-white/40">Дата (MSK)</label>
                                            <CustomDatePicker
                                                value={dayStatusDate}
                                                onChange={setDayStatusDate}
                                                placeholder="Дата"
                                            />
                                        </div>
                                        {canManagePoints && canManageSelectedAssistant ? (
                                            <div className="relative">
                                                <label className="mb-1 block text-xs text-white/40">Изменение корректировки баллов</label>
                                                <input
                                                    type="number"
                                                    step="0.0001"
                                                    value={pointsForm.adjustmentChange}
                                                    onChange={(event) => setPointsForm({ adjustmentChange: event.target.value })}
                                                    className="w-full rounded-lg border border-white/10 bg-black/40 py-2 pl-3 pr-24 text-sm text-white focus:border-white/20 focus:outline-none"
                                                    placeholder="На сколько изменить корректировку"
                                                />
                                                {pointsForm.adjustmentChange && !Number.isNaN(Number(pointsForm.adjustmentChange)) && (
                                                    <div className="pointer-events-none absolute bottom-2 right-3 rounded-md border border-white/5 bg-white/10 px-2 py-0.5 text-xs font-semibold text-white/90 shadow-sm">
                                                        Новая корректировка: {formatMetricValue(
                                                            Number(selectedDayStatus?.manual_points_delta ?? 0) + Number(pointsForm.adjustmentChange),
                                                            4,
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                        ) : null}
                                    </div>
                                    <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
                                        <div className="rounded-lg border border-white/5 bg-white/5 px-3 py-2">
                                            <div className="text-xs text-white/40">Авто за день</div>
                                            <div className="font-semibold text-white">{formatMetricValue(selectedDayStatus?.spec_points_auto ?? 0, 4)}</div>
                                        </div>
                                        <div className="rounded-lg border border-white/5 bg-white/5 px-3 py-2">
                                            <div className="text-xs text-white/40">Текущая корректировка</div>
                                            <div className="font-semibold text-white">{formatMetricValue(selectedDayStatus?.manual_points_delta ?? 0, 4)}</div>
                                        </div>
                                        <div className="rounded-lg border border-white/5 bg-white/5 px-3 py-2">
                                            <div className="text-xs text-white/40">Итог после санкций</div>
                                            <div className="font-semibold text-white">
                                                {formatMetricValue(selectedAssistant.net_points ?? selectedAssistant.gross_points ?? 0)}
                                            </div>
                                        </div>
                                    </div>
                                    {canManagePoints && canManageSelectedAssistant && (
                                        <button
                                            type="button"
                                            onClick={() => void handlePointsAdjust()}
                                            disabled={busy || dayStatusLoading}
                                            className="w-full rounded-lg bg-blue-500/20 px-3 py-2 text-sm font-medium text-blue-300 disabled:opacity-50 hover:bg-blue-500/30"
                                        >
                                            Сохранить корректировку баллов
                                        </button>
                                    )}
                                </div>

                                <div className="space-y-3 rounded-2xl border border-white/5 bg-black/20 p-4">
                                    <div className="flex items-center gap-2 font-semibold text-white">
                                        <Timer className="h-4 w-4 text-cyan-300" />
                                        MChat
                                    </div>
                                    {dayStatusError && (
                                        <InlineState message={dayStatusError} tone="danger" />
                                    )}
                                    <div className="grid grid-cols-1 gap-3 md:grid-cols-[180px_minmax(0,1fr)]">
                                        <div>
                                            <label className="mb-1 block text-xs text-white/40">Дата (MSK)</label>
                                            <CustomDatePicker
                                                value={dayStatusDate}
                                                onChange={setDayStatusDate}
                                                placeholder="Дата"
                                            />
                                        </div>
                                        {canManagePoints && canManageSelectedAssistant ? (
                                            <div>
                                                <label className="mb-1 block text-xs text-white/40">Количество MChat за день</label>
                                                <input
                                                    type="number"
                                                    min="0"
                                                    step="1"
                                                    value={mchatForm.count}
                                                    onChange={(event) => setMchatForm({ count: event.target.value })}
                                                    className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:border-white/20 focus:outline-none"
                                                    placeholder="Введите итоговое количество MChat"
                                                />
                                            </div>
                                        ) : null}
                                    </div>
                                    <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
                                        <div className="rounded-lg border border-white/5 bg-white/5 px-3 py-2">
                                            <div className="text-xs text-white/40">Текущее значение</div>
                                            <div className="font-semibold text-white">{selectedDayStatus?.mchat_count ?? 0}</div>
                                        </div>
                                        <div className="rounded-lg border border-white/5 bg-white/5 px-3 py-2">
                                            <div className="text-xs text-white/40">Жалоб за день</div>
                                            <div className="font-semibold text-white">{selectedDayStatus?.complaints_count ?? 0}</div>
                                        </div>
                                    </div>
                                    {canManagePoints && canManageSelectedAssistant && (
                                        <button
                                            type="button"
                                            onClick={() => void handleMchatSave()}
                                            disabled={busy || dayStatusLoading}
                                            className="w-full rounded-lg bg-cyan-500/20 px-3 py-2 text-sm font-medium text-cyan-200 disabled:opacity-50 hover:bg-cyan-500/30"
                                        >
                                            Сохранить MChat за день
                                        </button>
                                    )}
                                </div>
                            </div>

                            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                                <div className="space-y-4 rounded-2xl border border-white/5 bg-black/20 p-4">
                                    <div className="flex items-center justify-between">
                                        <div className="font-semibold text-white">Ручная санкция</div>
                                        {canManageSanctions && (
                                            <button
                                                type="button"
                                                onClick={() => setManualSanctionForm((current) => {
                                                    const nextMetric = getAvailableWorkoffMetrics(current.workoffItems)[0];
                                                    if (!nextMetric) return current;
                                                    return {
                                                        ...current,
                                                        workoffItems: [
                                                            ...current.workoffItems,
                                                            { ...createEmptyWorkoffDraft(), metric: nextMetric },
                                                        ],
                                                    };
                                                })}
                                                disabled={getAvailableWorkoffMetrics(manualSanctionForm.workoffItems).length === 0}
                                                className="rounded-lg border border-emerald-400/20 bg-emerald-500/10 px-3 py-1.5 text-sm text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
                                            >
                                                + Добавить отработку
                                            </button>
                                        )}
                                    </div>

                                    {canManageSanctions && canManageSelectedAssistant && (
                                        <>
                                            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                                <div>
                                                    <label className="mb-1 block text-xs text-white/50">Тип санкции</label>
                                                    <CustomDropdown
                                                        value={manualSanctionForm.kind}
                                                        onChange={(value) => setManualSanctionForm((current) => ({
                                                            ...current,
                                                            kind: value as SanctionKind,
                                                            amount: ['check', 'oral', 'strict'].includes(value as SanctionKind) ? '1' : current.amount,
                                                        }))}
                                                        options={[
                                                            { value: 'check', label: 'Галка' },
                                                            { value: 'point', label: 'Штрафной балл' },
                                                            { value: 'percent', label: 'Штрафной %' },
                                                            { value: 'oral', label: 'Устный' },
                                                            { value: 'strict', label: 'Строгий' },
                                                        ]}
                                                    />
                                                </div>
                                                {!['check', 'oral', 'strict'].includes(manualSanctionForm.kind) && (
                                                    <div>
                                                        <label className="mb-1 block text-xs text-white/50">Размер</label>
                                                        <input
                                                            type="number"
                                                            min="0"
                                                            step="0.0001"
                                                            value={manualSanctionForm.amount}
                                                            onChange={(event) => setManualSanctionForm((current) => ({ ...current, amount: event.target.value }))}
                                                            className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:border-white/20 focus:outline-none"
                                                            placeholder="1"
                                                        />
                                                    </div>
                                                )}
                                                {['oral', 'strict'].includes(manualSanctionForm.kind) && (
                                                    <div>
                                                        <label className="mb-1 block text-xs text-white/50">Дата автоснятия</label>
                                                        <CustomDatePicker
                                                            value={manualSanctionForm.auto_relief_date}
                                                            onChange={(value) => setManualSanctionForm((current) => ({ ...current, auto_relief_date: value }))}
                                                        />
                                                    </div>
                                                )}
                                            </div>

                                            {manualSanctionForm.workoffItems.length > 0 && (
                                                <div className="space-y-3">
                                                    {manualSanctionForm.workoffItems.map((item) => (
                                                        <div key={item.local_id} className="space-y-3 rounded-xl border border-white/10 bg-white/[0.04] p-3">
                                                            <div className="flex items-center justify-between">
                                                                <div className="text-sm text-white/75">Отработка</div>
                                                                <button
                                                                    type="button"
                                                                    onClick={() => setManualSanctionForm((current) => ({
                                                                        ...current,
                                                                        workoffItems: current.workoffItems.filter((entry) => entry.local_id !== item.local_id),
                                                                    }))}
                                                                    className="rounded-lg p-2 text-rose-200 hover:bg-rose-500/10"
                                                                >
                                                                    <Trash2 className="h-4 w-4" />
                                                                </button>
                                                            </div>
                                                            <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                                                                <div>
                                                                    <label className="mb-1 block text-xs text-white/50">Тип</label>
                                                                    <CustomDropdown
                                                                        value={item.metric}
                                                                        onChange={(value) => setManualSanctionForm((current) => ({
                                                                            ...current,
                                                                            workoffItems: current.workoffItems.map((entry) => (
                                                                                entry.local_id === item.local_id
                                                                                    ? { ...entry, metric: value as WorkoffMetric }
                                                                                    : entry
                                                                            )),
                                                                        }))}
                                                                        options={getAvailableWorkoffMetrics(manualSanctionForm.workoffItems, item.local_id)
                                                                            .concat(item.metric)
                                                                            .filter((metric, index, array) => array.indexOf(metric) === index)
                                                                            .map((metric) => ({
                                                                                value: metric,
                                                                                label: workoffMetricLabel(metric),
                                                                            }))}
                                                                    />
                                                                </div>
                                                                <div>
                                                                    <label className="mb-1 block text-xs text-white/50">X от нормы</label>
                                                                    <input
                                                                        type="number"
                                                                        min="0"
                                                                        step="0.1"
                                                                        value={item.multiplier}
                                                                        onChange={(event) => setManualSanctionForm((current) => ({
                                                                            ...current,
                                                                            workoffItems: current.workoffItems.map((entry) => (
                                                                                entry.local_id === item.local_id
                                                                                    ? { ...entry, multiplier: event.target.value }
                                                                                    : entry
                                                                            )),
                                                                        }))}
                                                                        className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:border-white/20 focus:outline-none"
                                                                    />
                                                                </div>
                                                                <div>
                                                                    <label className="mb-1 block text-xs text-white/50">Период с</label>
                                                                    <CustomDatePicker
                                                                        value={item.period_start}
                                                                        onChange={(value) => setManualSanctionForm((current) => ({
                                                                            ...current,
                                                                            workoffItems: current.workoffItems.map((entry) => (
                                                                                entry.local_id === item.local_id
                                                                                    ? { ...entry, period_start: value }
                                                                                    : entry
                                                                            )),
                                                                        }))}
                                                                    />
                                                                </div>
                                                                <div>
                                                                    <label className="mb-1 block text-xs text-white/50">Период по</label>
                                                                    <CustomDatePicker
                                                                        value={item.period_end}
                                                                        onChange={(value) => setManualSanctionForm((current) => ({
                                                                            ...current,
                                                                            workoffItems: current.workoffItems.map((entry) => (
                                                                                entry.local_id === item.local_id
                                                                                    ? { ...entry, period_end: value }
                                                                                    : entry
                                                                            )),
                                                                        }))}
                                                                    />
                                                                </div>
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}

                                            {manualSanctionForm.workoffItems.length > 0 && (
                                                <div className="space-y-3 rounded-xl border border-white/10 bg-sky-500/5 p-4">
                                                    <div className="flex items-center justify-between gap-3">
                                                        <div className="text-sm font-medium text-white">Предпросмотр отработки</div>
                                                        {manualWorkoffPreviewLoading && (
                                                            <div className="text-xs text-white/45">Обновляем...</div>
                                                        )}
                                                    </div>
                                                    <div className="text-xs text-white/45">
                                                        U/O не засчитываются и продлевают отработку.
                                                    </div>
                                                    {manualWorkoffPreviewError && (
                                                        <InlineState message={manualWorkoffPreviewError} tone="danger" />
                                                    )}
                                                    {!manualWorkoffPreviewLoading && manualWorkoffPreview.length === 0 && !manualWorkoffPreviewError && (
                                                        <InlineState message="Добавьте валидную отработку, чтобы увидеть расчет." />
                                                    )}
                                                    <div className="space-y-3">
                                                        {manualWorkoffPreview.map((previewAssistant) => (
                                                            <div key={previewAssistant.assistant_id} className="space-y-3 rounded-xl border border-white/10 bg-black/20 p-3">
                                                                <div className="flex items-center justify-between gap-3">
                                                                    <div className="text-sm font-medium text-white/80">
                                                                        {previewAssistant.nickname || selectedAssistant.nickname || `Ассистент ${previewAssistant.assistant_id}`}
                                                                    </div>
                                                                    <div className="text-xs text-white/45">ID {previewAssistant.assistant_id}</div>
                                                                </div>
                                                                <div className="space-y-2">
                                                                    {previewAssistant.items.map((item, index) => {
                                                                        const itemKey = workoffPreviewItemKey(previewAssistant.assistant_id, item.metric, index);
                                                                        const isExpanded = Boolean(manualWorkoffPreviewExpanded[itemKey]);
                                                                        const days = item.days ?? [];
                                                                        const hasDays = days.length > 0;
                                                                        return (
                                                                            <div key={itemKey} className="space-y-2 rounded-lg border border-white/10 bg-white/[0.03] p-3">
                                                                                <div className="flex flex-wrap items-center gap-2 text-sm">
                                                                                    <span className="text-white/80">{workoffMetricLabel(item.metric)}</span>
                                                                                    <span className="text-white/45">x{formatMetricValue(item.multiplier, 1)}</span>
                                                                                    <span className="text-white/45">{item.period_start} - {item.period_end}</span>
                                                                                </div>
                                                                                <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-5">
                                                                                    <div className="rounded-lg border border-white/10 bg-black/20 px-2 py-1 text-white/70">
                                                                                        Дней по плану: {formatWorkoffCounter(item.required_work_days)}
                                                                                    </div>
                                                                                    <div className="rounded-lg border border-white/10 bg-black/20 px-2 py-1 text-white/70">
                                                                                        Учтено: {formatWorkoffCounter(item.counted_work_days)}
                                                                                    </div>
                                                                                    <div className="rounded-lg border border-white/10 bg-black/20 px-2 py-1 text-white/70">
                                                                                        У/О: {formatWorkoffCounter(item.uo_days_count)}
                                                                                    </div>
                                                                                    <div className="rounded-lg border border-white/10 bg-black/20 px-2 py-1 text-white/70 md:col-span-2">
                                                                                        Статус: {workoffStatusLabel(item.status)}
                                                                                    </div>
                                                                                    <div className="rounded-lg border border-white/10 bg-black/20 px-2 py-1 text-white/70 md:col-span-2">
                                                                                        Эффективная дата окончания: {item.effective_period_end || 'не определена'}
                                                                                    </div>
                                                                                </div>
                                                                                {hasDays && (
                                                                                    <div className="pt-1">
                                                                                        <button
                                                                                            type="button"
                                                                                            className="inline-flex items-center rounded-lg border border-white/10 bg-black/20 px-3 py-1.5 text-xs text-white/75 transition hover:bg-white/10 hover:text-white"
                                                                                            onClick={() => setManualWorkoffPreviewExpanded((current) => ({ ...current, [itemKey]: !current[itemKey] }))}
                                                                                        >
                                                                                            {isExpanded ? 'Скрыть дни' : `Показать дни (${days.length})`}
                                                                                        </button>
                                                                                    </div>
                                                                                )}
                                                                                {hasDays && isExpanded && (
                                                                                    <WorkoffDaysList
                                                                                        days={days}
                                                                                        keyPrefix={`preview-${previewAssistant.assistant_id}-${item.metric}-${index}`}
                                                                                    />
                                                                                )}
                                                                            </div>
                                                                        );
                                                                    })}
                                                                </div>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}

                                            <button
                                                type="button"
                                                onClick={() => void handleManualSanctionCreate()}
                                                disabled={busy}
                                                className="w-full rounded-lg bg-rose-500/20 px-3 py-2 text-sm font-medium text-rose-200 disabled:opacity-50 hover:bg-rose-500/30"
                                            >
                                                Выдать санкцию
                                            </button>
                                        </>
                                    )}
                                </div>

                                <div className="space-y-3 rounded-2xl border border-white/5 bg-black/20 p-4">
                                    <div className="font-semibold text-white">Активные санкции</div>
                                    {sanctionsError && (
                                        <InlineState message={sanctionsError} tone="danger" />
                                    )}
                                    {sanctionsLoading && activeSanctions.length === 0 ? (
                                        <div className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-6 text-center text-white/45">
                                            Загрузка санкций...
                                        </div>
                                    ) : activeSanctions.length === 0 ? (
                                        <div className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-6 text-center text-white/45">
                                            У ассистента нет активных санкций
                                        </div>
                                    ) : (
                                        <div className="space-y-3">
                                            {activeSanctions.map((sanction) => {
                                                const needsAmount = !['check', 'oral', 'strict'].includes(sanction.kind);
                                                return (
                                                    <div key={sanction.sanction_id} className="space-y-3 rounded-xl border border-white/10 bg-white/[0.04] p-4">
                                                        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                                                            <div>
                                                                <div className="font-medium text-white">
                                                                    {sanction.kind} · остаток {sanction.active_amount}
                                                                </div>
                                                                <div className="text-xs text-white/45">
                                                                    Источник: {getSourceTypeLabel(sanction.source_type)} · Выдано: {formatDateTime(sanction.display_issued_at ?? sanction.issued_at)}
                                                                </div>
                                                                {sanction.auto_relief_date && (
                                                                    <div className="text-xs text-white/45">Автоснятие: {sanction.auto_relief_date}</div>
                                                                )}
                                                            </div>
                                                            <div className="text-xs text-white/50">
                                                                {sanction.workoff_progress_summary.has_workoff
                                                                    ? `Отработка ${sanction.workoff_progress_summary.completed_items}/${sanction.workoff_progress_summary.total_items}`
                                                                    : 'Без отработки'}
                                                            </div>
                                                        </div>
                                                        {sanction.workoff_progress_summary.items.length > 0 && (
                                                            <div className="space-y-3">
                                                                {sanction.workoff_progress_summary.items.map((item, index) => (
                                                                    <div key={`${sanction.sanction_id}-${item.metric}-${index}`} className="space-y-3 rounded-xl border border-white/10 bg-black/30 p-3">
                                                                        <div className="flex flex-wrap items-center justify-between gap-3">
                                                                            <div className="text-sm text-white/80">
                                                                                {workoffMetricLabel(item.metric as WorkoffMetric)} · x{formatMetricValue(item.multiplier, 1)} · {item.period_start} - {item.period_end}
                                                                            </div>
                                                                            <div className="text-xs text-white/50">
                                                                                {workoffStatusLabel(item.status)}
                                                                            </div>
                                                                        </div>
                                                                        <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-5">
                                                                            <div className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-white/70">
                                                                                План: {formatWorkoffCounter(item.required_work_days ?? item.target_amount)}
                                                                            </div>
                                                                            <div className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-white/70">
                                                                                Учтено: {formatWorkoffCounter(item.counted_work_days ?? item.amount_done)}
                                                                            </div>
                                                                            <div className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-white/70">
                                                                                У/О: {formatWorkoffCounter(item.uo_days_count)}
                                                                            </div>
                                                                            <div className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-white/70 md:col-span-2">
                                                                                Эффективная дата конца: {item.effective_period_end || 'не определена'}
                                                                            </div>
                                                                        </div>
                                                                        {item.days && item.days.length > 0 ? (
                                                                            <WorkoffDaysList
                                                                                days={item.days}
                                                                                keyPrefix={`sanction-${sanction.sanction_id}-${item.metric}-${index}`}
                                                                            />
                                                                        ) : (
                                                                            <div className="text-xs text-white/45">
                                                                                {formatMetricValue(item.amount_done ?? 0)}/{formatMetricValue(item.target_amount ?? 0)}
                                                                            </div>
                                                                        )}
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        )}
                                                        {canManageSanctions && canManageSelectedAssistant ? (
                                                            <div className="flex flex-col gap-3 md:flex-row md:items-end">
                                                                {needsAmount && (
                                                                    <div className="w-full md:w-48">
                                                                        <label className="mb-1 block text-xs text-white/50">Сколько снять</label>
                                                                        <input
                                                                            type="number"
                                                                            min="0"
                                                                            step="0.0001"
                                                                            value={manualReliefAmountBySanctionId[sanction.sanction_id] ?? ''}
                                                                            onChange={(event) => setManualReliefAmountBySanctionId((current) => ({
                                                                                ...current,
                                                                                [sanction.sanction_id]: event.target.value,
                                                                            }))}
                                                                            className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:border-white/20 focus:outline-none"
                                                                            placeholder={String(sanction.active_amount)}
                                                                        />
                                                                    </div>
                                                                )}
                                                                <button
                                                                    type="button"
                                                                    onClick={() => void handleManualRelief(sanction)}
                                                                    disabled={busy}
                                                                    className="rounded-lg bg-amber-500/20 px-4 py-2 text-sm font-medium text-amber-200 disabled:opacity-50 hover:bg-amber-500/30"
                                                                >
                                                                    {needsAmount ? 'Снять вручную' : 'Снять полностью'}
                                                                </button>
                                                            </div>
                                                        ) : null}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            </div>

                            {canShowRoleSection && (
                                <div className="flex flex-col gap-4 rounded-2xl border border-white/5 bg-black/20 p-4 lg:flex-row lg:items-center">
                                    <div className="flex-1">
                                        <label className="mb-1 block text-xs text-white/50">Роль</label>
                                        {canEditSelectedAssistant ? (
                                            <CustomDropdown
                                                value={selectedAssistant.role || 'employee'}
                                                onChange={(value) => void handleRoleChange(value)}
                                                disabled={busy || roleOptions.length === 0}
                                                options={roleOptions}
                                            />
                                        ) : (
                                            <div className="space-y-2">
                                                <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/75">
                                                    {getRoleLabel(selectedAssistant.role)}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                    {canDeactivateSelectedAssistant ? (
                                        <button
                                            type="button"
                                            onClick={() => void handleDeactivateAssistant()}
                                            disabled={busy}
                                            className="flex items-center justify-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm font-medium text-red-300 transition-colors hover:bg-red-500/20 disabled:opacity-50"
                                        >
                                            <Trash2 className="h-4 w-4" />
                                            Деактивировать
                                        </button>
                                    ) : null}
                                </div>
                            )}

                            <div className="space-y-3 rounded-2xl border border-white/5 bg-black/20 p-4">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2 font-semibold text-white">
                                        <Timer className="h-4 w-4 text-indigo-400" />
                                        Ручная сессия
                                    </div>
                                </div>

                                {canManageSessions && canManageSelectedAssistant && (
                                    <>
                                        {optionsError && manualSessionForm.target_type !== 'manual' && (
                                            <InlineState
                                                message={`${optionsError}. Для manual-сессии форма продолжит работать.`}
                                                tone="warning"
                                            />
                                        )}
                                        <div className="space-y-3">
                                            <div className="flex flex-wrap items-center gap-2">
                                                <div className="w-36 shrink-0">
                                                    <CustomDropdown
                                                        value={manualSessionForm.target_type}
                                                        onChange={(value) => setManualSessionForm((current) => ({
                                                            ...current,
                                                            target_type: value,
                                                            target_id: '',
                                                            priority: '0',
                                                        }))}
                                                        options={[
                                                            { value: 'streamer', label: 'Стример' },
                                                            { value: 'event', label: 'Событие' },
                                                            { value: 'manual', label: 'Manual' },
                                                        ]}
                                                    />
                                                </div>
                                                {manualSessionForm.target_type !== 'manual' && (
                                                    <div className="min-w-[200px] flex-1">
                                                        <CustomSelect
                                                            options={manualTargetOptions}
                                                            value={manualSessionForm.target_id}
                                                            onChange={(value) => {
                                                                const targetId = String(value);
                                                                const defaultPriority = manualSessionForm.target_type === 'event'
                                                                    ? eventPriorityById[targetId] ?? 0
                                                                    : streamerPriorityById[targetId] ?? 0;
                                                                setManualSessionForm((current) => ({
                                                                    ...current,
                                                                    target_id: targetId,
                                                                    priority: String(defaultPriority),
                                                                }));
                                                            }}
                                                            placeholder={
                                                                optionsLoading
                                                                    ? 'Loading...'
                                                                    : manualTargetOptions.length > 0
                                                                        ? (manualSessionForm.target_type === 'event' ? 'Выберите событие' : 'Выберите стримера')
                                                                        : (manualSessionForm.target_type === 'event' ? 'Нет доступных событий' : 'Нет доступных стримеров')
                                                            }
                                                        />
                                                    </div>
                                                )}
                                                {manualSessionForm.target_type === 'manual' && (
                                                    <input
                                                        type="text"
                                                        value={manualSessionForm.target_name}
                                                        onChange={(event) => setManualSessionForm((current) => ({ ...current, target_name: event.target.value }))}
                                                        className="min-w-[150px] flex-1 rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                                                        placeholder="Название"
                                                    />
                                                )}
                                            </div>
                                            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                                                <div>
                                                    <label className="mb-1 block text-xs text-white/40">Дата начала</label>
                                                    <CustomDatePicker
                                                        value={splitDateTime(manualSessionForm.started_at).date}
                                                        onChange={(value) => setManualSessionForm((current) => ({
                                                            ...current,
                                                            started_at: mergeDateTimePart(current.started_at, 'date', value),
                                                        }))}
                                                        placeholder="Дата"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="mb-1 block text-xs text-white/40">Время начала</label>
                                                    <CustomTimePicker
                                                        value={splitDateTime(manualSessionForm.started_at).time}
                                                        onChange={(value) => setManualSessionForm((current) => ({
                                                            ...current,
                                                            started_at: mergeDateTimePart(current.started_at, 'time', value),
                                                        }))}
                                                        placeholder="--:--"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="mb-1 block text-xs text-white/40">Дата конца</label>
                                                    <CustomDatePicker
                                                        value={splitDateTime(manualSessionForm.ended_at).date}
                                                        onChange={(value) => setManualSessionForm((current) => ({
                                                            ...current,
                                                            ended_at: mergeDateTimePart(current.ended_at, 'date', value),
                                                        }))}
                                                        placeholder="Дата"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="mb-1 block text-xs text-white/40">Время конца</label>
                                                    <CustomTimePicker
                                                        value={splitDateTime(manualSessionForm.ended_at).time}
                                                        onChange={(value) => setManualSessionForm((current) => ({
                                                            ...current,
                                                            ended_at: mergeDateTimePart(current.ended_at, 'time', value),
                                                        }))}
                                                        placeholder="--:--"
                                                    />
                                                </div>
                                            </div>
                                            <div className="flex flex-wrap items-center gap-3">
                                                <div className="flex items-center gap-2">
                                                    <span className="text-xs text-white/40">Приоритет:</span>
                                                    <input
                                                        type="number"
                                                        min="0"
                                                        max="3"
                                                        value={manualSessionForm.priority}
                                                        onChange={(event) => setManualSessionForm((current) => ({ ...current, priority: event.target.value }))}
                                                        disabled={manualSessionForm.is_probation}
                                                        className="w-16 rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white disabled:opacity-50"
                                                    />
                                                </div>
                                                <label className="group flex cursor-pointer items-center gap-2">
                                                    <div className="relative">
                                                        <input
                                                            type="checkbox"
                                                            className="peer sr-only"
                                                            checked={manualSessionForm.is_probation}
                                                            onChange={(event) => setManualSessionForm((current) => ({ ...current, is_probation: event.target.checked }))}
                                                        />
                                                        <div className="h-5 w-10 rounded-full bg-white/10 transition-colors peer-checked:bg-yellow-500/50" />
                                                        <div className="absolute left-1 top-1 h-3 w-3 rounded-full bg-white/40 transition-transform peer-checked:translate-x-5 peer-checked:bg-white" />
                                                    </div>
                                                    <span className="text-xs text-white/60 transition-colors group-hover:text-white">Стажерский</span>
                                                </label>
                                            </div>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={() => void handleManualSessionCreate()}
                                            disabled={busy}
                                            className="rounded-lg bg-indigo-500/20 px-3 py-2 text-sm font-medium text-indigo-300 disabled:opacity-50 hover:bg-indigo-500/30"
                                        >
                                            Добавить ручную сессию
                                        </button>
                                    </>
                                )}
                            </div>

                            <div className="space-y-3 rounded-2xl border border-white/5 bg-black/20 p-4">
                                <div className="flex items-center justify-between">
                                    <div className="font-semibold text-white">Сессии ассистента</div>
                                    {canViewSessions && (
                                        <button
                                            type="button"
                                            onClick={() => void refreshSelectionData()}
                                            disabled={busy || sessionsLoading || assistantLoading || sanctionsLoading || dayStatusLoading}
                                            className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/80 disabled:opacity-50 hover:bg-white/10"
                                        >
                                            <RefreshCw className="h-3.5 w-3.5" />
                                            Обновить
                                        </button>
                                    )}
                                </div>
                                {!canViewSessions ? (
                                    <InlineState message="Сессии недоступны для вашей роли." tone="warning" />
                                ) : sessionsError ? (
                                    <InlineState message={sessionsError} tone="danger" />
                                ) : sessionsLoading && sessions.length === 0 ? (
                                    <div className="text-sm text-white/40">Загрузка сессий...</div>
                                ) : (
                                    <div className="max-h-[440px] space-y-2 overflow-y-auto pr-1">
                                        {sessions.length === 0 ? (
                                            <div className="text-sm text-white/40">Сессий нет</div>
                                        ) : sessions.map((session) => (
                                            <div key={session.id} className="space-y-2 rounded-xl border border-white/10 bg-white/5 p-3">
                                                <div className="flex flex-wrap items-center gap-3 text-xs text-white/50">
                                                    <span>ID: {session.id}</span>
                                                    <span>Тип: {session.target_type || '—'}</span>
                                                    <span>Цель: {getTargetDisplayName(session)}</span>
                                                    <span>Начало: {formatDateTime(session.started_at)}</span>
                                                    <span>Конец: {formatDateTime(session.ended_at)}</span>
                                                    <span>Длительность: {session.duration_seconds ?? 0} сек.</span>
                                                    <span>Баллы: {session.credited_points ?? 0}</span>
                                                    {session.is_probation ? (
                                                        <span className="font-medium text-yellow-400/80">Стажерский</span>
                                                    ) : (
                                                        <span>Приоритет: {session.priority_override ?? session.priority_auto ?? 0}</span>
                                                    )}
                                                </div>
                                                {editingSessionId === session.id && canManageSessions && canManageSelectedAssistant && (
                                                    <div className="space-y-3">
                                                        {optionsError && sessionEdit.target_type !== 'manual' && (
                                                            <InlineState message={optionsError} tone="warning" />
                                                        )}
                                                        <div className="flex flex-wrap items-center gap-2">
                                                            <div className="w-36 shrink-0">
                                                                <CustomDropdown
                                                                    value={sessionEdit.target_type}
                                                                    onChange={(value) => setSessionEdit((current) => ({
                                                                        ...current,
                                                                        target_type: value,
                                                                        target_id: '',
                                                                        priority_override: '0',
                                                                    }))}
                                                                    options={[
                                                                        { value: 'streamer', label: 'Стример' },
                                                                        { value: 'event', label: 'Событие' },
                                                                        { value: 'manual', label: 'Manual' },
                                                                    ]}
                                                                />
                                                            </div>
                                                            {sessionEdit.target_type !== 'manual' && (
                                                                <div className="min-w-[200px] flex-1">
                                                                    <CustomSelect
                                                                        options={editTargetOptions}
                                                                        value={sessionEdit.target_id}
                                                                        onChange={(value) => {
                                                                            const targetId = String(value);
                                                                            const defaultPriority = sessionEdit.target_type === 'event'
                                                                                ? eventPriorityById[targetId] ?? 0
                                                                                : streamerPriorityById[targetId] ?? 0;
                                                                            setSessionEdit((current) => ({
                                                                                ...current,
                                                                                target_id: targetId,
                                                                                priority_override: String(defaultPriority),
                                                                            }));
                                                                        }}
                                                                        placeholder={
                                                                            optionsLoading
                                                                                ? 'Loading...'
                                                                                : editTargetOptions.length > 0
                                                                                    ? (sessionEdit.target_type === 'event' ? 'Выберите событие' : 'Выберите стримера')
                                                                                    : (sessionEdit.target_type === 'event' ? 'Нет доступных событий' : 'Нет доступных стримеров')
                                                                        }
                                                                    />
                                                                </div>
                                                            )}
                                                            {sessionEdit.target_type === 'manual' && (
                                                                <input
                                                                    type="text"
                                                                    value={sessionEdit.target_name}
                                                                    onChange={(event) => setSessionEdit((current) => ({ ...current, target_name: event.target.value }))}
                                                                    className="min-w-[150px] flex-1 rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                                                                    placeholder="Название"
                                                                />
                                                            )}
                                                        </div>
                                                        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                                                            <div>
                                                                <label className="mb-1 block text-xs text-white/40">Дата начала</label>
                                                                <CustomDatePicker
                                                                    value={splitDateTime(sessionEdit.started_at).date}
                                                                    onChange={(value) => setSessionEdit((current) => ({
                                                                        ...current,
                                                                        started_at: mergeDateTimePart(current.started_at, 'date', value),
                                                                    }))}
                                                                    placeholder="Дата"
                                                                />
                                                            </div>
                                                            <div>
                                                                <label className="mb-1 block text-xs text-white/40">Время начала</label>
                                                                <CustomTimePicker
                                                                    value={splitDateTime(sessionEdit.started_at).time}
                                                                    onChange={(value) => setSessionEdit((current) => ({
                                                                        ...current,
                                                                        started_at: mergeDateTimePart(current.started_at, 'time', value),
                                                                    }))}
                                                                    placeholder="--:--"
                                                                />
                                                            </div>
                                                            <div>
                                                                <label className="mb-1 block text-xs text-white/40">Дата конца</label>
                                                                <CustomDatePicker
                                                                    value={splitDateTime(sessionEdit.ended_at).date}
                                                                    onChange={(value) => setSessionEdit((current) => ({
                                                                        ...current,
                                                                        ended_at: mergeDateTimePart(current.ended_at, 'date', value),
                                                                    }))}
                                                                    placeholder="Дата"
                                                                />
                                                            </div>
                                                            <div>
                                                                <label className="mb-1 block text-xs text-white/40">Время конца</label>
                                                                <CustomTimePicker
                                                                    value={splitDateTime(sessionEdit.ended_at).time}
                                                                    onChange={(value) => setSessionEdit((current) => ({
                                                                        ...current,
                                                                        ended_at: mergeDateTimePart(current.ended_at, 'time', value),
                                                                    }))}
                                                                    placeholder="--:--"
                                                                />
                                                            </div>
                                                        </div>
                                                        <div className="flex items-center gap-4">
                                                            <div className="flex items-center gap-2">
                                                                <span className="text-xs text-white/40">Приоритет:</span>
                                                                <input
                                                                    type="number"
                                                                    min="0"
                                                                    max="3"
                                                                    value={sessionEdit.priority_override}
                                                                    onChange={(event) => setSessionEdit((current) => ({ ...current, priority_override: event.target.value }))}
                                                                    className="w-16 rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                                                                    disabled={sessionEdit.is_probation}
                                                                />
                                                            </div>
                                                            <label className="group flex cursor-pointer items-center gap-2">
                                                                <div className="relative">
                                                                    <input
                                                                        type="checkbox"
                                                                        className="peer sr-only"
                                                                        checked={sessionEdit.is_probation}
                                                                        onChange={(event) => setSessionEdit((current) => ({ ...current, is_probation: event.target.checked }))}
                                                                    />
                                                                    <div className="h-5 w-10 rounded-full bg-white/10 transition-colors peer-checked:bg-yellow-500/50" />
                                                                    <div className="absolute left-1 top-1 h-3 w-3 rounded-full bg-white/40 transition-transform peer-checked:translate-x-5 peer-checked:bg-white" />
                                                                </div>
                                                                <span className="text-xs text-white/60 transition-colors group-hover:text-white">Стажерский</span>
                                                            </label>
                                                        </div>
                                                    </div>
                                                )}
                                                <div className="flex items-center gap-2">
                                                    {canManageSessions && canManageSelectedAssistant ? (
                                                        editingSessionId === session.id ? (
                                                            <>
                                                                <button
                                                                    type="button"
                                                                    onClick={() => void handleSessionPatch(session.id)}
                                                                    disabled={busy}
                                                                    className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-xs text-blue-300 disabled:opacity-50 hover:bg-blue-500/20"
                                                                >
                                                                    Сохранить
                                                                </button>
                                                                <button
                                                                    type="button"
                                                                    onClick={() => {
                                                                        setEditingSessionId(null);
                                                                        setSessionEdit(createInitialSessionEditState());
                                                                    }}
                                                                    disabled={busy}
                                                                    className="rounded-lg border border-white/20 bg-white/5 px-3 py-1.5 text-xs text-white/70 disabled:opacity-50 hover:bg-white/10"
                                                                >
                                                                    Отмена
                                                                </button>
                                                            </>
                                                        ) : (
                                                            <button
                                                                type="button"
                                                                onClick={() => void beginEditingSession(session)}
                                                                disabled={busy}
                                                                className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-xs text-blue-300 disabled:opacity-50 hover:bg-blue-500/20"
                                                                >
                                                                    Редактировать
                                                                </button>
                                                        )
                                                    ) : canManageSessions ? (
                                                        <span className="text-xs text-white/40">Read-only</span>
                                                    ) : (
                                                        <span className="text-xs text-white/40">Read-only</span>
                                                    )}
                                                    {canManageSessions && canManageSelectedAssistant && (
                                                        <button
                                                            type="button"
                                                            onClick={() => void handleSessionDelete(session.id)}
                                                            disabled={busy}
                                                            className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs text-red-300 disabled:opacity-50 hover:bg-red-500/20"
                                                        >
                                                            Удалить
                                                        </button>
                                                    )}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </>
                    )}
                </div>
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

export default AssistantsManagement;
