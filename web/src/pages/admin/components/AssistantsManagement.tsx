import React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Check, Clipboard, Coins, RefreshCw, Timer, Trash2, Wrench } from 'lucide-react';
import { CustomSelect, CustomDropdown, CustomDatePicker, CustomTimePicker } from '../../../components/CustomInputs';
import ConfirmDialog from '../../../components/feedback/ConfirmDialog';
import NotificationToast from '../../../components/feedback/NotificationToast';
import { useConfirmDialog, usePopupToast } from '../../../components/feedback/hooks';
import type { ActiveSanction, Assistant, Event, SanctionDayStatus, Streamer } from '../../../types/domain';
import { unwrapApiData } from '../../../types/api';
import { parseMskDate, getMskDateOffsetStr, getMskNow, formatMskToLocal, formatToMskIso } from '../../../utils/datetime';
import { apiFetch } from '../../../api/client';

void React;

export type SpecSessionEndReason = 'manual_unclaim' | 'stream_end' | 'category_change' | 'admin_closed' | 'event_end' | 'event_rejected' | 'unknown';

interface AssistantSessionRecord {
    id: number;
    pr_id: number | string;
    target_type?: string | null;
    target_id?: number | string | null;
    target_name?: string | null;
    started_at: string;
    ended_at?: string | null;
    duration_seconds?: number | null;
    end_reason?: SpecSessionEndReason | null;
    is_probation?: boolean;
    priority_auto?: number | null;
    priority_override?: number | null;
    rate_auto?: number | null;
    credited_points?: number | null;
    deleted_at?: string | null;
    delete_reason?: string | null;
}

interface SelectOption {
    value: string;
    label: string;
}

type SanctionKind = 'check' | 'point' | 'percent' | 'oral' | 'strict';
type WorkoffMetric = 'spec' | 'complaints' | 'mchat';

interface WorkoffDraftItem {
    local_id: string;
    metric: WorkoffMetric;
    multiplier: string;
    period_start: string;
    period_end: string;
}

const formatDateTime = (value?: string | null) => {
    return formatMskToLocal(value);
};

const formatMetricValue = (value?: number | null, fractionDigits = 2) => {
    const numeric = Number(value ?? 0);
    if (!Number.isFinite(numeric)) return '0';
    return numeric
        .toFixed(fractionDigits)
        .replace(/(\.\d*?[1-9])0+$/, '$1')
        .replace(/\.0+$/, '')
        .replace(/\.00$/, '');
};

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

/** Split 'YYYY-MM-DDTHH:mm' into { date: 'YYYY-MM-DD', time: 'HH:mm' } */
const splitDateTime = (combined: string) => {
    const [date = '', time = ''] = combined.split('T');
    return { date, time };
};

/** Merge date and time parts back into 'YYYY-MM-DDTHH:mm' */
const mergeDateTimePart = (current: string, part: 'date' | 'time', value: string) => {
    const { date, time } = splitDateTime(current);
    if (part === 'date') return value ? `${value}T${time || '00:00'}` : '';
    return date ? `${date}T${value || '00:00'}` : '';
};

const parseLocalDateTimeToIso = (localValue: string) => {
    if (!localValue) return null;
    return localValue.length === 16 ? localValue + ':00' : localValue;
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

const makeStreamerOption = (streamer: Streamer): SelectOption => {
    const status = streamer.is_online ? 'онлайн' : 'оффлайн';
    return {
        value: String(streamer.streamer_id),
        label: `${streamer.streamer_name} · ID ${streamer.streamer_id} · ${status}`,
    };
};

const makeEventOption = (event: Event): SelectOption => {
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

const AssistantsManagement = () => {
    const { toast, showToast, closeToast } = usePopupToast(3000);
    const { confirm, dialogProps } = useConfirmDialog();
    const [assistants, setAssistants] = useState<Assistant[]>([]);
    const [selectedPrId, setSelectedPrId] = useState<string | null>(null);
    const [copiedId, setCopiedId] = useState(false);

    const handleCopyId = () => {
        if (!selectedPrId) return;
        navigator.clipboard.writeText(selectedPrId)
            .then(() => {
                setCopiedId(true);
                setTimeout(() => setCopiedId(false), 1500);
                showToast('PR ID скопирован');
            })
            .catch(() => {
                showToast('Не удалось скопировать PR ID', 'error');
            });
    };
    const [selectedAssistant, setSelectedAssistant] = useState<Assistant | null>(null);
    const [sessions, setSessions] = useState<AssistantSessionRecord[]>([]);
    const [activeSanctions, setActiveSanctions] = useState<ActiveSanction[]>([]);
    const [selectedDayStatus, setSelectedDayStatus] = useState<SanctionDayStatus | null>(null);
    const [streamerOptions, setStreamerOptions] = useState<SelectOption[]>([]);
    const [eventOptions, setEventOptions] = useState<SelectOption[]>([]);
    const [streamerNameById, setStreamerNameById] = useState<Record<string, string>>({});
    const [eventNameById, setEventNameById] = useState<Record<string, string>>({});
    const [streamerPriorityById, setStreamerPriorityById] = useState<Record<string, number>>({});
    const [eventPriorityById, setEventPriorityById] = useState<Record<string, number>>({});
    const [optionsLoading, setOptionsLoading] = useState(false);
    const [optionsError, setOptionsError] = useState<string | null>(null);
    const [search, setSearch] = useState('');
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [sessionModeWarning, setSessionModeWarning] = useState<string | null>(null);
    const [editingSessionId, setEditingSessionId] = useState<number | null>(null);
    const [sessionEdit, setSessionEdit] = useState({
        target_type: 'streamer',
        target_id: '',
        target_name: '',
        started_at: '',
        ended_at: '',
        priority_override: '',
        is_probation: false,
    });

    const [dayStatusDate, setDayStatusDate] = useState(getMskDateOffsetStr(0));
    const [pointsForm, setPointsForm] = useState({ adjustmentChange: '' });
    const [mchatForm, setMchatForm] = useState({ count: '' });
    const [manualSanctionForm, setManualSanctionForm] = useState({
        kind: 'point' as SanctionKind,
        amount: '1',
        auto_relief_date: '',
        workoffItems: [] as WorkoffDraftItem[],
    });
    const [manualReliefAmountBySanctionId, setManualReliefAmountBySanctionId] = useState<Record<string, string>>({});
    const manualWindow = getDefaultManualWindow();
    const [manualSessionForm, setManualSessionForm] = useState({
        target_type: 'streamer',
        target_id: '',
        target_name: '',
        started_at: manualWindow.started_at,
        ended_at: manualWindow.ended_at,
        is_probation: false,
        priority: '0',
    });

    const filteredAssistants = useMemo(() => {
        const query = search.trim().toLowerCase();
        if (!query) return assistants;
        return assistants.filter((assistant) =>
            assistant.nickname.toLowerCase().includes(query)
            || String(assistant.pr_id).includes(query)
        );
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

    const canUseStreamerOrEventSelectors = !optionsLoading && !optionsError;

    const manualTargetOptions = useMemo(() => {
        const baseOptions = manualSessionForm.target_type === 'event' ? eventOptions : streamerOptions;
        const prefix = manualSessionForm.target_type === 'event' ? 'Событие ID' : 'Стример ID';
        return ensureOptionExists(baseOptions, manualSessionForm.target_id || undefined, prefix);
    }, [manualSessionForm.target_type, manualSessionForm.target_id, eventOptions, streamerOptions]);

    const editTargetOptions = useMemo(() => {
        const baseOptions = sessionEdit.target_type === 'event' ? eventOptions : streamerOptions;
        const prefix = sessionEdit.target_type === 'event' ? 'Событие ID' : 'Стример ID';
        return ensureOptionExists(baseOptions, sessionEdit.target_id || undefined, prefix);
    }, [sessionEdit.target_type, sessionEdit.target_id, eventOptions, streamerOptions]);

    const fetchAssistants = useCallback(async () => {
        const response = await apiFetch('/api/assistants');
        if (!response.ok) throw new Error('Не удалось загрузить ассистентов');
        const json = await response.json() as unknown;
        const data = unwrapApiData<Assistant[] | { assistants: Assistant[] }>(json);
        const normalized = Array.isArray(data) ? data : data.assistants;
        const list = Array.isArray(normalized) ? normalized : [];
        setAssistants(list);
        if (list.length > 0) {
            setSelectedPrId((prev) => prev ?? String(list[0].pr_id));
        }
    }, []);

    const fetchSessionTargetOptions = useCallback(async () => {
        setOptionsLoading(true);
        setOptionsError(null);
        try {
            const [streamersResponse, eventsResponse] = await Promise.all([
                apiFetch('/api/streamers'),
                apiFetch('/api/events'),
            ]);

            if (!streamersResponse.ok || !eventsResponse.ok) {
                throw new Error('Не удалось загрузить списки стримеров/событий');
            }

            const streamersJson = await streamersResponse.json() as unknown;
            const eventsJson = await eventsResponse.json() as unknown;

            const streamersData = unwrapApiData<{ streamers?: Streamer[] } | Streamer[]>(streamersJson);
            const eventsData = unwrapApiData<Event[] | { events: Event[] }>(eventsJson);

            const rawStreamers = Array.isArray(streamersData)
                ? streamersData
                : (streamersData.streamers || []);
            const rawEvents = Array.isArray(eventsData)
                ? eventsData
                : ((eventsData && 'events' in eventsData) ? eventsData.events : []);

            const sortedStreamers = [...rawStreamers].sort((a, b) => {
                const onlineCmp = Number(Boolean(b.is_online)) - Number(Boolean(a.is_online));
                if (onlineCmp !== 0) return onlineCmp;
                return (a.streamer_name || '').localeCompare(b.streamer_name || '', 'ru');
            });
            const sortedEvents = [...rawEvents].sort((a, b) => {
                const activeCmp = Number(Boolean(b.is_active)) - Number(Boolean(a.is_active));
                if (activeCmp !== 0) return activeCmp;
                return (a.name || '').localeCompare(b.name || '', 'ru');
            });

            const nextStreamerNameById: Record<string, string> = {};
            const nextEventNameById: Record<string, string> = {};
            const nextStreamerPriorityById: Record<string, number> = {};
            const nextEventPriorityById: Record<string, number> = {};
            sortedStreamers.forEach((streamer) => {
                nextStreamerNameById[String(streamer.streamer_id)] = streamer.streamer_name;
                nextStreamerPriorityById[String(streamer.streamer_id)] = streamer.priority ?? 0;
            });
            sortedEvents.forEach((event) => {
                nextEventNameById[String(event.id)] = event.name;
                nextEventPriorityById[String(event.id)] = event.priority ?? 0;
            });

            setStreamerNameById(nextStreamerNameById);
            setEventNameById(nextEventNameById);
            setStreamerPriorityById(nextStreamerPriorityById);
            setEventPriorityById(nextEventPriorityById);
            setStreamerOptions(sortedStreamers.map(makeStreamerOption));
            setEventOptions(sortedEvents.map(makeEventOption));
        } catch (error: unknown) {
            setOptionsError(error instanceof Error ? error.message : 'Не удалось загрузить списки стримеров/событий');
        } finally {
            setOptionsLoading(false);
        }
    }, []);

    const fetchAssistantDetail = useCallback(async (prId: string) => {
        const response = await apiFetch(`/api/assistants/${prId}`);
        if (!response.ok) throw new Error('Не удалось загрузить профиль ассистента');
        const json = await response.json() as unknown;
        const data = unwrapApiData<Assistant>(json);
        setSelectedAssistant(data);
    }, []);

    const fetchAssistantSessions = useCallback(async (prId: string) => {
        const response = await apiFetch(`/api/assistants/${prId}/sessions?limit=50`);

        if (response.ok) {
            const json = await response.json() as unknown;
            const data = unwrapApiData<AssistantSessionRecord[]>(json);
            setSessions(Array.isArray(data) ? data : []);
            setSessionModeWarning(null);
            return;
        }

        // Fallback: if auth header is stripped somewhere in the chain,
        // still show read-only streamer sessions from public spec endpoint.
        if (response.status === 401 || response.status === 403) {
            const fallback = await apiFetch(`/api/spec/sessions/${prId}?limit=50`);
            if (fallback.ok) {
                const fallbackJson = await fallback.json() as unknown;
                const fallbackData = unwrapApiData<Array<{
                    id: number;
                    pr_id: number | string;
                    streamer_id?: number | string | null;
                    started_at: string;
                    ended_at?: string | null;
                    duration_seconds?: number | null;
                    end_reason?: SpecSessionEndReason | null;
                }>>(fallbackJson);
                const normalized = Array.isArray(fallbackData)
                    ? fallbackData.map((item) => ({
                        id: item.id,
                        pr_id: item.pr_id,
                        target_type: 'streamer',
                        target_id: item.streamer_id ?? null,
                        target_name: null,
                        started_at: item.started_at,
                        ended_at: item.ended_at ?? null,
                        duration_seconds: item.duration_seconds ?? null,
                        end_reason: item.end_reason ?? null,
                        credited_points: null,
                    } satisfies AssistantSessionRecord))
                    : [];
                setSessions(normalized);
                setSessionModeWarning('Сессии загружены в режиме read-only. Для админ-редактирования выполните повторный вход.');
                return;
            }
        }

        throw new Error('Не удалось загрузить сессии ассистента');
    }, []);

    const fetchAssistantActiveSanctions = useCallback(async (prId: string) => {
        const response = await apiFetch(`/api/assistants/${prId}/sanctions/active`);
        if (!response.ok) {
            throw new Error('Не удалось загрузить активные санкции ассистента');
        }
        const json = await response.json() as unknown;
        const data = unwrapApiData<ActiveSanction[]>(json);
        setActiveSanctions(Array.isArray(data) ? data : []);
    }, []);

    const fetchAssistantDayStatus = useCallback(async (prId: string, workDate: string) => {
        const response = await apiFetch(`/api/assistants/${prId}/day-status?date=${workDate}`);
        if (!response.ok) {
            throw new Error('Не удалось загрузить дневной статус ассистента');
        }
        const json = await response.json() as unknown;
        const data = unwrapApiData<SanctionDayStatus>(json);
        setSelectedDayStatus(data);
    }, []);

    const refreshSelectedAssistant = useCallback(async (prId: string) => {
        const [detailResult, sessionsResult, assistantsResult, sanctionsResult] = await Promise.allSettled([
            fetchAssistantDetail(prId),
            fetchAssistantSessions(prId),
            fetchAssistants(),
            fetchAssistantActiveSanctions(prId),
        ]);

        if (detailResult.status === 'rejected') {
            throw detailResult.reason;
        }
        if (assistantsResult.status === 'rejected') {
            throw assistantsResult.reason;
        }
        if (sessionsResult.status === 'rejected') {
            setSessions([]);
            setSessionModeWarning(null);
            showToast(
                sessionsResult.reason instanceof Error
                    ? sessionsResult.reason.message
                    : 'Не удалось загрузить сессии ассистента',
                'error',
            );
        }
        if (sanctionsResult.status === 'rejected') {
            setActiveSanctions([]);
            showToast(
                sanctionsResult.reason instanceof Error
                    ? sanctionsResult.reason.message
                    : 'Не удалось загрузить активные санкции ассистента',
                'error',
            );
        }
    }, [fetchAssistantActiveSanctions, fetchAssistantDetail, fetchAssistantSessions, fetchAssistants, showToast]);

    useEffect(() => {
        const load = async () => {
            try {
                setLoading(true);
                await Promise.all([fetchAssistants(), fetchSessionTargetOptions()]);
            } catch (error: unknown) {
                showToast(error instanceof Error ? error.message : 'Ошибка загрузки', 'error');
            } finally {
                setLoading(false);
            }
        };
        void load();
    }, [fetchAssistants, fetchSessionTargetOptions, showToast]);

    useEffect(() => {
        if (!selectedPrId) return;
        const loadSelected = async () => {
            try {
                setBusy(true);
                await refreshSelectedAssistant(selectedPrId);
            } catch (error: unknown) {
                showToast(error instanceof Error ? error.message : 'Ошибка загрузки данных ассистента', 'error');
            } finally {
                setBusy(false);
            }
        };
        void loadSelected();
    }, [refreshSelectedAssistant, selectedPrId, showToast]);

    useEffect(() => {
        if (!selectedPrId) {
            setSelectedDayStatus(null);
            return;
        }
        const loadDayStatus = async () => {
            try {
                await fetchAssistantDayStatus(selectedPrId, dayStatusDate);
            } catch (error: unknown) {
                setSelectedDayStatus(null);
                showToast(error instanceof Error ? error.message : 'Не удалось загрузить дневной статус ассистента', 'error');
            }
        };
        void loadDayStatus();
    }, [dayStatusDate, fetchAssistantDayStatus, selectedPrId, showToast]);

    const runMutation = async (
        endpoint: string,
        method: 'POST' | 'PATCH' | 'PUT' | 'DELETE',
        payload?: Record<string, unknown>,
    ) => {
        if (!selectedPrId) return;
        setBusy(true);
        try {
            const response = await apiFetch(endpoint, {
                method,
                headers: {
                    'Content-Type': 'application/json',
                },
                body: payload ? JSON.stringify(payload) : undefined,
            });
            const json = await response.json().catch(() => ({} as unknown));
            if (!response.ok) {
                throw new Error((json as { detail?: string }).detail || 'Операция не выполнена');
            }
            await refreshSelectedAssistant(selectedPrId);
            await fetchAssistantDayStatus(selectedPrId, dayStatusDate);
            showToast('Изменения сохранены');
        } catch (error: unknown) {
            showToast(error instanceof Error ? error.message : 'Операция не выполнена', 'error');
        } finally {
            setBusy(false);
        }
    };

    const buildWorkoffItemsPayload = (items: WorkoffDraftItem[]) => {
        const seen = new Set<WorkoffMetric>();
        return items
            .map((item) => ({
                metric: item.metric,
                multiplier: Number(item.multiplier),
                period_start: item.period_start,
                period_end: item.period_end,
            }))
            .filter(
                (item) => item.period_start
                    && item.period_end
                    && Number.isFinite(item.multiplier)
                    && item.multiplier > 0
                    && (seen.has(item.metric) ? false : (seen.add(item.metric), true)),
            );
    };

    const handleManualSanctionCreate = async () => {
        if (!selectedPrId) return;
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
        const payload = {
            assistant_id: selectedPrId,
            kind: manualSanctionForm.kind,
            ...(needsAmount ? { amount } : {}),
            ...(needsWarningDate ? { auto_relief_date: manualSanctionForm.auto_relief_date } : {}),
            workoff_items: buildWorkoffItemsPayload(manualSanctionForm.workoffItems),
        };
        await runMutation('/api/assistant-sanctions', 'POST', payload);
    };

    const handleManualRelief = async (sanction: ActiveSanction) => {
        const rawAmount = manualReliefAmountBySanctionId[sanction.sanction_id] ?? '';
        const amount = ['check', 'oral', 'strict'].includes(sanction.kind) ? 1 : toNumberOrUndefined(rawAmount);
        if (!amount || amount <= 0) {
            showToast('Укажите корректный размер снятия', 'error');
            return;
        }
        await runMutation(`/api/assistant-sanctions/${sanction.sanction_id}/reliefs`, 'POST', {
            amount,
            relief_type: 'manual',
        });
        setManualReliefAmountBySanctionId((prev) => {
            const next = { ...prev };
            delete next[sanction.sanction_id];
            return next;
        });
    };

    const handlePointsAdjust = async () => {
        if (!selectedPrId) return;
        const adjustmentChange = toNumberOrUndefined(pointsForm.adjustmentChange);
        if (adjustmentChange === undefined || adjustmentChange === 0) {
            showToast('Укажите, на сколько изменить корректировку баллов', 'error');
            return;
        }
        await runMutation('/api/assistant-day-points', 'POST', {
            assistant_id: selectedPrId,
            work_date: dayStatusDate,
            delta_points: Number((Number(selectedDayStatus?.manual_points_delta ?? 0) + adjustmentChange).toFixed(4)),
        });
        setPointsForm({ adjustmentChange: '' });
    };

    const handleMchatSave = async () => {
        if (!selectedPrId) return;
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
        await runMutation('/api/assistant-day-mchat', 'PUT', {
            assistant_id: selectedPrId,
            work_date: dayStatusDate,
            mchat_count: parsed,
        });
        setMchatForm({ count: '' });
    };

    const handleManualSessionCreate = async () => {
        if (!selectedPrId) return;
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
        const targetType = manualSessionForm.target_type;
        const targetOptions = targetType === 'event' ? eventOptions : streamerOptions;
        if (targetType !== 'manual' && !canUseStreamerOrEventSelectors) {
            showToast(optionsError || 'Справочники стримеров/событий пока недоступны', 'error');
            return;
        }
        if (targetType !== 'manual' && targetOptions.length === 0) {
            showToast(targetType === 'event' ? 'Нет доступных событий' : 'Нет доступных стримеров', 'error');
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
        if (manualSessionForm.target_type === 'manual') {
            // manual sessions no longer require a comment
        }
        const targetName = parsedTargetId !== undefined
            ? (
                targetType === 'event'
                    ? eventNameById[String(parsedTargetId)]
                    : streamerNameById[String(parsedTargetId)]
            ) || null
            : null;
        await runMutation(`/api/assistants/${selectedPrId}/session`, 'POST', {
            target_type: manualSessionForm.target_type,
            target_id: manualSessionForm.target_type === 'manual'
                ? null
                : parsedTargetId,
            target_name: manualSessionForm.target_type === 'manual'
                ? (manualSessionForm.target_name.trim() || null)
                : targetName,
            started_at: startedAtIso,
            ended_at: endedAtIso,
            is_probation: manualSessionForm.is_probation,
            priority: Number(manualSessionForm.priority || '0'),
        });
    };

    const handleSessionPatch = async (sessionId: number) => {
        if (!selectedPrId) return;
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
        const targetType = sessionEdit.target_type;
        const targetOptions = targetType === 'event' ? eventOptions : streamerOptions;
        if (targetType !== 'manual' && !canUseStreamerOrEventSelectors) {
            showToast(optionsError || 'Справочники стримеров/событий пока недоступны', 'error');
            return;
        }
        if (targetType !== 'manual' && targetOptions.length === 0) {
            showToast(targetType === 'event' ? 'Нет доступных событий' : 'Нет доступных стримеров', 'error');
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
        if (sessionEdit.target_type === 'manual') {
            // manual sessions no longer require a comment
        }
        const payload: Record<string, unknown> = {
            target_type: sessionEdit.target_type,
            target_id: sessionEdit.target_type === 'manual' ? null : parsedTargetId,
            target_name: sessionEdit.target_type === 'manual'
                ? (sessionEdit.target_name.trim() || null)
                : null,
            started_at: startedAtIso,
            ended_at: endedAtIso,
            is_probation: sessionEdit.is_probation,
        };
        const defaultPriority = sessionEdit.target_type === 'event'
            ? eventPriorityById[String(parsedTargetId)] ?? 0
            : sessionEdit.target_type === 'streamer'
                ? streamerPriorityById[String(parsedTargetId)] ?? 0
                : 0;

        if (sessionEdit.priority_override.trim() !== '') {
            const parsedOverride = Number(sessionEdit.priority_override);
            if (parsedOverride === defaultPriority) {
                payload.priority_override = null;
            } else {
                payload.priority_override = parsedOverride;
            }
        } else {
            payload.priority_override = null;
        }

        await runMutation(`/api/assistants/${selectedPrId}/sessions/${sessionId}`, 'PATCH', payload);
        setEditingSessionId(null);
    };

    const handleSessionDelete = async (sessionId: number) => {
        if (!selectedPrId) return;
        await runMutation(`/api/assistants/${selectedPrId}/sessions/${sessionId}`, 'DELETE');
    };

    const handleRoleChange = async (newRole: string) => {
        if (!selectedPrId || !selectedAssistant) return;
        setBusy(true);
        try {
            const response = await apiFetch('/api/assistants', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    pr_id: selectedPrId,
                    nickname: selectedAssistant.nickname,
                    role: newRole,
                    experience_days: selectedAssistant.experience_days ?? 0,
                }),
            });
            const json = await response.json().catch(() => ({} as unknown));
            if (!response.ok) {
                throw new Error((json as { detail?: string }).detail || 'Не удалось сменить роль');
            }
            await refreshSelectedAssistant(selectedPrId);
            showToast(`Роль изменена на ${newRole}`);
        } catch (error: unknown) {
            showToast(error instanceof Error ? error.message : 'Ошибка смены роли', 'error');
        } finally {
            setBusy(false);
        }
    };

    const handleDeleteAssistant = async () => {
        if (!selectedPrId || !selectedAssistant) return;
        const confirmed = await confirm({
            title: 'Удалить ассистента?',
            message: <>Ассистент <span className="text-white font-semibold">{selectedAssistant.nickname}</span> будет удален без возможности восстановления.</>,
            confirmLabel: 'Удалить',
            tone: 'danger',
        });
        if (!confirmed) return;
        setBusy(true);
        try {
            const response = await apiFetch(`/api/assistants/${selectedPrId}`, {
                method: 'DELETE',
            });
            if (!response.ok) {
                const json = await response.json().catch(() => ({} as unknown));
                throw new Error((json as { detail?: string }).detail || 'Не удалось удалить ассистента');
            }
            setSelectedPrId(null);
            setSelectedAssistant(null);
            setSessions([]);
            await fetchAssistants();
            setSessionModeWarning(null);
            showToast('Ассистент удален');
        } catch (error: unknown) {
            showToast(error instanceof Error ? error.message : 'Ошибка удаления ассистента', 'error');
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="space-y-6 animate-[fadeIn_0.3s_ease-in-out]">
            <div className="flex items-center gap-4 border-b border-white/10 pb-6">
                <div className="w-12 h-12 rounded-xl bg-indigo-500/20 text-indigo-400 flex items-center justify-center border border-indigo-500/30">
                    <Wrench className="w-6 h-6" />
                </div>
                <div>
                    <h2 className="text-2xl font-bold text-white">Ассистенты</h2>
                    <p className="text-white/60">Управление баллами, санкциями, ролями и сессиями</p>
                </div>
            </div>

            {optionsError && (
                <div className="px-4 py-3 rounded-xl flex items-center gap-3 bg-yellow-500/10 border border-yellow-500/20 text-yellow-200">
                    <AlertCircle className="w-5 h-5" />
                    {optionsError}. Для `manual`-спека форма продолжит работать.
                </div>
            )}

            {sessionModeWarning && (
                <div className="px-4 py-3 rounded-xl flex items-center gap-3 bg-amber-500/10 border border-amber-500/20 text-amber-200">
                    <AlertCircle className="w-5 h-5" />
                    {sessionModeWarning}
                </div>
            )}

            <div className="space-y-4">
                {/* Поиск + горизонтальные карточки */}
                <div className="bg-black/20 border border-white/5 rounded-2xl p-4 space-y-3">
                    <input
                        type="text"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder="Поиск: ник или PR ID"
                        className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-sm text-white placeholder:text-white/30 focus:outline-none focus:border-white/20 transition-colors"
                    />
                    <div className="flex flex-wrap gap-2">
                        {loading ? (
                            <div className="text-white/50 text-sm py-1">Загрузка...</div>
                        ) : filteredAssistants.length === 0 ? (
                            <div className="text-white/40 text-sm py-1">Ничего не найдено</div>
                        ) : (
                            filteredAssistants.map((assistant) => (
                                <button
                                    key={assistant.pr_id}
                                    onClick={() => setSelectedPrId(String(assistant.pr_id))}
                                    className={`text-left rounded-xl border px-3 py-2 transition-all text-sm shrink-0 ${String(assistant.pr_id) === selectedPrId
                                        ? 'border-indigo-400/40 bg-indigo-500/10 text-indigo-200 shadow-[0_0_10px_rgba(99,102,241,0.15)]'
                                        : 'border-white/10 bg-white/5 text-white/70 hover:bg-white/10 hover:text-white/90 hover:border-white/20'
                                        }`}
                                >
                                    <div className="font-medium">{assistant.nickname}</div>
                                </button>
                            ))
                        )}
                    </div>
                </div>

                <div className="space-y-4">
                    {!selectedAssistant ? (
                        <div className="bg-black/20 border border-white/5 rounded-2xl p-8 text-white/50 text-center">
                            Выберите ассистента для управления
                        </div>
                    ) : (
                        <>
                            <div className="bg-black/20 border border-white/5 rounded-2xl p-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7 gap-3">
                                <div className="bg-white/5 rounded-xl p-3">
                                    <div className="text-xs text-white/50">Ник</div>
                                    <div className="flex items-center gap-2">
                                        <div className="text-white font-semibold">{selectedAssistant.nickname}</div>
                                        <button
                                            onClick={handleCopyId}
                                            title={`Скопировать PR ID: ${selectedPrId}`}
                                            className="ml-auto p-1 rounded-lg text-white/30 hover:text-white/80 hover:bg-white/10 transition-all"
                                        >
                                            {copiedId
                                                ? <Check className="w-3.5 h-3.5 text-green-400" />
                                                : <Clipboard className="w-3.5 h-3.5" />}
                                        </button>
                                    </div>
                                </div>
                                <div className="bg-white/5 rounded-xl p-3">
                                    <div className="text-xs text-white/50">Баллы до санкций</div>
                                    <div className="text-green-300 font-semibold">{formatMetricValue(selectedAssistant.gross_points ?? 0)}</div>
                                </div>
                                <div className="bg-white/5 rounded-xl p-3">
                                    <div className="text-xs text-white/50">Баллы после санкций</div>
                                    <div className="text-emerald-200 font-semibold">
                                        {formatMetricValue(selectedAssistant.net_points ?? selectedAssistant.gross_points ?? 0)}
                                    </div>
                                </div>
                                <div className="bg-white/5 rounded-xl p-3">
                                    <div className="text-xs text-white/50">Активные штрафные баллы</div>
                                    <div className="text-amber-300 font-semibold">{formatMetricValue(sanctionTotals.point)}</div>
                                </div>
                                <div className="bg-white/5 rounded-xl p-3">
                                    <div className="text-xs text-white/50">Активный штраф, %</div>
                                    <div className="text-amber-300 font-semibold">{formatMetricValue(sanctionTotals.percent)}%</div>
                                </div>
                                <div className="bg-white/5 rounded-xl p-3">
                                    <div className="text-xs text-white/50">Галки</div>
                                    <div className="text-white font-semibold">{formatMetricValue(sanctionTotals.check)}</div>
                                </div>
                                <div className="bg-white/5 rounded-xl p-3">
                                    <div className="text-xs text-white/50">Устный / строгий</div>
                                    <div className="text-white font-semibold">{formatMetricValue(sanctionTotals.oral)} / {formatMetricValue(sanctionTotals.strict)}</div>
                                </div>
                            </div>

                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                                <div className="bg-black/20 border border-white/5 rounded-2xl p-4 space-y-3">
                                    <div className="text-white font-semibold flex items-center gap-2">
                                        <Coins className="w-4 h-4 text-green-400" />Баллы
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-[180px_minmax(0,1fr)] gap-3">
                                        <div>
                                            <label className="text-xs text-white/40 mb-1 block">Дата (MSK)</label>
                                            <CustomDatePicker
                                                value={dayStatusDate}
                                                onChange={setDayStatusDate}
                                                placeholder="Дата"
                                            />
                                        </div>
                                        <div className="relative">
                                            <label className="text-xs text-white/40 mb-1 block">Изменение корректировки баллов</label>
                                            <input
                                                type="number"
                                                step="0.0001"
                                                value={pointsForm.adjustmentChange}
                                                onChange={(e) => setPointsForm({ adjustmentChange: e.target.value })}
                                                className="w-full bg-black/40 border border-white/10 rounded-lg pl-3 pr-24 py-2 text-sm text-white focus:outline-none focus:border-white/20"
                                                placeholder="На сколько изменить корректировку"
                                            />
                                            {pointsForm.adjustmentChange && !isNaN(Number(pointsForm.adjustmentChange)) && (
                                                <div className="absolute right-3 bottom-2 text-xs font-semibold px-2 py-0.5 rounded-md bg-white/10 text-white/90 shadow-sm border border-white/5 pointer-events-none">
                                                    Новая корректировка: {formatMetricValue(
                                                        Number(selectedDayStatus?.manual_points_delta ?? 0) + Number(pointsForm.adjustmentChange),
                                                        4,
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
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
                                    <button
                                        onClick={() => void handlePointsAdjust()}
                                        disabled={busy}
                                        className="w-full rounded-lg px-3 py-2 text-sm font-medium bg-blue-500/20 text-blue-300 hover:bg-blue-500/30 disabled:opacity-50"
                                    >
                                        Сохранить корректировку баллов
                                    </button>
                                </div>

                                <div className="bg-black/20 border border-white/5 rounded-2xl p-4 space-y-3">
                                    <div className="text-white font-semibold flex items-center gap-2">
                                        <Timer className="w-4 h-4 text-cyan-300" />MChat
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-[180px_minmax(0,1fr)] gap-3">
                                        <div>
                                            <label className="text-xs text-white/40 mb-1 block">Дата (MSK)</label>
                                            <CustomDatePicker
                                                value={dayStatusDate}
                                                onChange={setDayStatusDate}
                                                placeholder="Дата"
                                            />
                                        </div>
                                        <div className="relative">
                                            <label className="text-xs text-white/40 mb-1 block">Количество MChat за день</label>
                                            <input
                                                type="number"
                                                min="0"
                                                step="1"
                                                value={mchatForm.count}
                                                onChange={(e) => setMchatForm({ count: e.target.value })}
                                                className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-white/20"
                                                placeholder="Введите итоговое количество MChat"
                                            />
                                        </div>
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                                        <div className="rounded-lg border border-white/5 bg-white/5 px-3 py-2">
                                            <div className="text-xs text-white/40">Текущее значение</div>
                                            <div className="font-semibold text-white">{selectedDayStatus?.mchat_count ?? 0}</div>
                                        </div>
                                        <div className="rounded-lg border border-white/5 bg-white/5 px-3 py-2">
                                            <div className="text-xs text-white/40">Жалоб за день</div>
                                            <div className="font-semibold text-white">{selectedDayStatus?.complaints_count ?? 0}</div>
                                        </div>
                                    </div>
                                    <button
                                        onClick={() => void handleMchatSave()}
                                        disabled={busy}
                                        className="w-full rounded-lg px-3 py-2 text-sm font-medium bg-cyan-500/20 text-cyan-200 hover:bg-cyan-500/30 disabled:opacity-50"
                                    >
                                        Сохранить MChat за день
                                    </button>
                                </div>
                            </div>

                            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                                <div className="bg-black/20 border border-white/5 rounded-2xl p-4 space-y-4">
                                    <div className="flex items-center justify-between">
                                        <div className="text-white font-semibold">Ручная санкция</div>
                                        <button
                                            type="button"
                                            onClick={() => setManualSanctionForm((prev) => {
                                                const nextMetric = getAvailableWorkoffMetrics(prev.workoffItems)[0];
                                                if (!nextMetric) return prev;
                                                return {
                                                    ...prev,
                                                    workoffItems: [
                                                        ...prev.workoffItems,
                                                        { ...createEmptyWorkoffDraft(), metric: nextMetric },
                                                    ],
                                                };
                                            })}
                                            disabled={getAvailableWorkoffMetrics(manualSanctionForm.workoffItems).length === 0}
                                            className="rounded-lg px-3 py-1.5 text-sm border border-emerald-400/20 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20"
                                        >
                                            + Добавить отработку
                                        </button>
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                        <div>
                                            <label className="text-xs text-white/50 mb-1 block">Тип санкции</label>
                                            <CustomDropdown
                                                value={manualSanctionForm.kind}
                                                onChange={(value) => setManualSanctionForm((prev) => ({
                                                    ...prev,
                                                    kind: value as SanctionKind,
                                                    amount: ['check', 'oral', 'strict'].includes(value as SanctionKind) ? '1' : prev.amount,
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
                                                <label className="text-xs text-white/50 mb-1 block">Размер</label>
                                                <input
                                                    type="number"
                                                    min="0"
                                                    step="0.0001"
                                                    value={manualSanctionForm.amount}
                                                    onChange={(e) => setManualSanctionForm((prev) => ({ ...prev, amount: e.target.value }))}
                                                    className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-white/20"
                                                    placeholder="1"
                                                />
                                            </div>
                                        )}
                                        {['oral', 'strict'].includes(manualSanctionForm.kind) && (
                                            <div>
                                                <label className="text-xs text-white/50 mb-1 block">Дата автоснятия</label>
                                                <CustomDatePicker
                                                    value={manualSanctionForm.auto_relief_date}
                                                    onChange={(value) => setManualSanctionForm((prev) => ({ ...prev, auto_relief_date: value }))}
                                                />
                                            </div>
                                        )}
                                    </div>

                                    {manualSanctionForm.workoffItems.length > 0 && (
                                        <div className="space-y-3">
                                            {manualSanctionForm.workoffItems.map((item) => (
                                                <div key={item.local_id} className="rounded-xl border border-white/10 bg-white/[0.04] p-3 space-y-3">
                                                    <div className="flex items-center justify-between">
                                                        <div className="text-sm text-white/75">Отработка</div>
                                                        <button
                                                            type="button"
                                                            onClick={() => setManualSanctionForm((prev) => ({
                                                                ...prev,
                                                                workoffItems: prev.workoffItems.filter((entry) => entry.local_id !== item.local_id),
                                                            }))}
                                                            className="rounded-lg p-2 text-rose-200 hover:bg-rose-500/10"
                                                        >
                                                            <Trash2 className="w-4 h-4" />
                                                        </button>
                                                    </div>
                                                    <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                                                        <div>
                                                            <label className="text-xs text-white/50 mb-1 block">Тип</label>
                                                            <CustomDropdown
                                                                value={item.metric}
                                                                onChange={(value) => setManualSanctionForm((prev) => ({
                                                                    ...prev,
                                                                    workoffItems: prev.workoffItems.map((entry) => entry.local_id === item.local_id ? { ...entry, metric: value as WorkoffMetric } : entry),
                                                                }))}
                                                                options={getAvailableWorkoffMetrics(manualSanctionForm.workoffItems, item.local_id)
                                                                    .concat(item.metric)
                                                                    .filter((metric, index, array) => array.indexOf(metric) === index)
                                                                    .map((metric) => ({
                                                                        value: metric,
                                                                        label: metric === 'spec'
                                                                            ? 'Спек'
                                                                            : metric === 'complaints'
                                                                                ? 'Жалобы'
                                                                                : 'MChat',
                                                                    }))}
                                                            />
                                                        </div>
                                                        <div>
                                                            <label className="text-xs text-white/50 mb-1 block">X от нормы</label>
                                                            <input
                                                                type="number"
                                                                min="0"
                                                                step="0.1"
                                                                value={item.multiplier}
                                                                onChange={(e) => setManualSanctionForm((prev) => ({
                                                                    ...prev,
                                                                    workoffItems: prev.workoffItems.map((entry) => entry.local_id === item.local_id ? { ...entry, multiplier: e.target.value } : entry),
                                                                }))}
                                                                className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-white/20"
                                                            />
                                                        </div>
                                                        <div>
                                                            <label className="text-xs text-white/50 mb-1 block">Период с</label>
                                                            <CustomDatePicker
                                                                value={item.period_start}
                                                                onChange={(value) => setManualSanctionForm((prev) => ({
                                                                    ...prev,
                                                                    workoffItems: prev.workoffItems.map((entry) => entry.local_id === item.local_id ? { ...entry, period_start: value } : entry),
                                                                }))}
                                                            />
                                                        </div>
                                                        <div>
                                                            <label className="text-xs text-white/50 mb-1 block">Период по</label>
                                                            <CustomDatePicker
                                                                value={item.period_end}
                                                                onChange={(value) => setManualSanctionForm((prev) => ({
                                                                    ...prev,
                                                                    workoffItems: prev.workoffItems.map((entry) => entry.local_id === item.local_id ? { ...entry, period_end: value } : entry),
                                                                }))}
                                                            />
                                                        </div>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}

                                    <button
                                        onClick={() => void handleManualSanctionCreate()}
                                        disabled={busy}
                                        className="w-full rounded-lg px-3 py-2 text-sm font-medium bg-rose-500/20 text-rose-200 hover:bg-rose-500/30 disabled:opacity-50"
                                    >
                                        Выдать санкцию
                                    </button>
                                </div>

                                <div className="bg-black/20 border border-white/5 rounded-2xl p-4 space-y-3">
                                    <div className="text-white font-semibold">Активные санкции</div>
                                    {activeSanctions.length === 0 ? (
                                        <div className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-6 text-center text-white/45">
                                            У ассистента нет активных санкций
                                        </div>
                                    ) : (
                                        <div className="space-y-3">
                                            {activeSanctions.map((sanction) => {
                                                const needsAmount = !['check', 'oral', 'strict'].includes(sanction.kind);
                                                return (
                                                    <div key={sanction.sanction_id} className="rounded-xl border border-white/10 bg-white/[0.04] p-4 space-y-3">
                                                        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
                                                            <div>
                                                                <div className="text-white font-medium">{sanction.kind} · остаток {sanction.active_amount}</div>
                                                                <div className="text-xs text-white/45">Источник: {getSourceTypeLabel(sanction.source_type)} · Выдано: {formatDateTime(sanction.display_issued_at ?? sanction.issued_at)}</div>
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
                                                            <div className="space-y-2">
                                                                {sanction.workoff_progress_summary.items.map((item, index) => (
                                                                    <div key={`${sanction.sanction_id}-${item.metric}-${index}`} className="rounded-lg bg-black/30 px-3 py-2 text-sm text-white/70">
                                                                        {item.metric} · x{item.multiplier} · {item.period_start} - {item.period_end} · {item.amount_done ?? 0}/{item.target_amount ?? 0}
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        )}
                                                        <div className="flex flex-col md:flex-row md:items-end gap-3">
                                                            {needsAmount && (
                                                                <div className="w-full md:w-48">
                                                                    <label className="text-xs text-white/50 mb-1 block">Сколько снять</label>
                                                                    <input
                                                                        type="number"
                                                                        min="0"
                                                                        step="0.0001"
                                                                        value={manualReliefAmountBySanctionId[sanction.sanction_id] ?? ''}
                                                                        onChange={(e) => setManualReliefAmountBySanctionId((prev) => ({
                                                                            ...prev,
                                                                            [sanction.sanction_id]: e.target.value,
                                                                        }))}
                                                                        className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-white/20"
                                                                        placeholder={String(sanction.active_amount)}
                                                                    />
                                                                </div>
                                                            )}
                                                            <button
                                                                onClick={() => void handleManualRelief(sanction)}
                                                                disabled={busy}
                                                                className="rounded-lg px-4 py-2 text-sm font-medium bg-amber-500/20 text-amber-200 hover:bg-amber-500/30 disabled:opacity-50"
                                                            >
                                                                {needsAmount ? 'Снять вручную' : 'Снять полностью'}
                                                            </button>
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            </div>


                            {/* Role & Delete */}
                            <div className="bg-black/20 border border-white/5 rounded-2xl p-4 flex items-center gap-4">
                                <div className="flex-1">
                                    <label className="text-xs text-white/50 mb-1 block">Роль</label>
                                    <CustomDropdown
                                        value={selectedAssistant.role || 'employee'}
                                        onChange={(v) => void handleRoleChange(v)}
                                        disabled={busy}
                                        options={[
                                            { value: 'junior_employee', label: 'Младший ассистент' },
                                            { value: 'employee', label: 'Ассистент' },
                                            { value: 'senior_employee', label: 'Старший ассистент' },
                                            { value: 'manager', label: 'Глава ассистентов' },
                                            { value: 'developer', label: 'Разработчик' },
                                        ]}
                                    />
                                </div>
                                <button
                                    onClick={() => void handleDeleteAssistant()}
                                    disabled={busy}
                                    className="mt-5 flex items-center gap-2 px-4 py-2 rounded-lg border border-red-500/30 bg-red-500/10 text-red-300 hover:bg-red-500/20 disabled:opacity-50 text-sm font-medium transition-colors"
                                >
                                    <Trash2 className="w-4 h-4" />
                                    Удалить
                                </button>
                            </div>


                            <div className="bg-black/20 border border-white/5 rounded-2xl p-4 space-y-3">
                                <div className="flex items-center justify-between">
                                    <div className="text-white font-semibold flex items-center gap-2"><Timer className="w-4 h-4 text-indigo-400" />Ручная сессия</div>

                                </div>
                                <div className="space-y-3">
                                    {/* Row 1: Target type + selector */}
                                    <div className="flex flex-wrap items-center gap-2">
                                        <div className="shrink-0 w-36">
                                            <CustomDropdown
                                                value={manualSessionForm.target_type}
                                                onChange={(v) => setManualSessionForm((prev) => ({
                                                    ...prev,
                                                    target_type: v,
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
                                            <div className="flex-1 min-w-[200px]">
                                                <CustomSelect
                                                    options={manualTargetOptions}
                                                    value={manualSessionForm.target_id}
                                                    onChange={(value) => {
                                                        const targetId = String(value);
                                                        const defaultPriority = manualSessionForm.target_type === 'event'
                                                            ? eventPriorityById[targetId] ?? 0
                                                            : streamerPriorityById[targetId] ?? 0;
                                                        setManualSessionForm((prev) => ({
                                                            ...prev,
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
                                                onChange={(e) => setManualSessionForm((prev) => ({ ...prev, target_name: e.target.value }))}
                                                className="flex-1 min-w-[150px] bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
                                                placeholder="Название"
                                            />
                                        )}
                                    </div>
                                    {/* Row 2: Date/time pickers */}
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                        <div>
                                            <label className="text-xs text-white/40 mb-1 block">Дата начала</label>
                                            <CustomDatePicker
                                                value={splitDateTime(manualSessionForm.started_at).date}
                                                onChange={(d) => setManualSessionForm((prev) => ({ ...prev, started_at: mergeDateTimePart(prev.started_at, 'date', d) }))}
                                                placeholder="Дата"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-xs text-white/40 mb-1 block">Время начала</label>
                                            <CustomTimePicker
                                                value={splitDateTime(manualSessionForm.started_at).time}
                                                onChange={(t) => setManualSessionForm((prev) => ({ ...prev, started_at: mergeDateTimePart(prev.started_at, 'time', t) }))}
                                                placeholder="--:--"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-xs text-white/40 mb-1 block">Дата конца</label>
                                            <CustomDatePicker
                                                value={splitDateTime(manualSessionForm.ended_at).date}
                                                onChange={(d) => setManualSessionForm((prev) => ({ ...prev, ended_at: mergeDateTimePart(prev.ended_at, 'date', d) }))}
                                                placeholder="Дата"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-xs text-white/40 mb-1 block">Время конца</label>
                                            <CustomTimePicker
                                                value={splitDateTime(manualSessionForm.ended_at).time}
                                                onChange={(t) => setManualSessionForm((prev) => ({ ...prev, ended_at: mergeDateTimePart(prev.ended_at, 'time', t) }))}
                                                placeholder="--:--"
                                            />
                                        </div>
                                    </div>
                                    {/* Row 3: Priority + probation */}
                                    <div className="flex flex-wrap items-center gap-3">
                                        <div className="flex items-center gap-2">
                                            <span className="text-xs text-white/40">Приоритет:</span>
                                            <input
                                                type="number"
                                                min="0"
                                                max="3"
                                                value={manualSessionForm.priority}
                                                onChange={(e) => setManualSessionForm((prev) => ({ ...prev, priority: e.target.value }))}
                                                disabled={manualSessionForm.is_probation}
                                                className="w-16 bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white disabled:opacity-50"
                                            />
                                        </div>
                                        <label className="flex items-center gap-2 cursor-pointer group">
                                            <div className="relative">
                                                <input
                                                    type="checkbox"
                                                    className="sr-only peer"
                                                    checked={manualSessionForm.is_probation}
                                                    onChange={(e) => setManualSessionForm((prev) => ({ ...prev, is_probation: e.target.checked }))}
                                                />
                                                <div className="w-10 h-5 bg-white/10 rounded-full peer peer-checked:bg-yellow-500/50 transition-colors"></div>
                                                <div className="absolute left-1 top-1 w-3 h-3 bg-white/40 rounded-full peer-checked:translate-x-5 peer-checked:bg-white transition-transform"></div>
                                            </div>
                                            <span className="text-xs text-white/60 group-hover:text-white transition-colors">Стажерский</span>
                                        </label>
                                    </div>
                                </div>
                                <button
                                    onClick={() => void handleManualSessionCreate()}
                                    disabled={busy}
                                    className="rounded-lg px-3 py-2 text-sm font-medium bg-indigo-500/20 text-indigo-300 hover:bg-indigo-500/30 disabled:opacity-50"
                                >
                                    Добавить ручную сессию
                                </button>
                            </div>

                            <div className="bg-black/20 border border-white/5 rounded-2xl p-4 space-y-3">
                                <div className="flex items-center justify-between">
                                    <div className="text-white font-semibold">Сессии ассистента</div>
                                    <button
                                        onClick={() => selectedPrId && void refreshSelectedAssistant(selectedPrId)}
                                        disabled={busy}
                                        className="inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg border border-white/10 bg-white/5 text-white/80 hover:bg-white/10 disabled:opacity-50"
                                    >
                                        <RefreshCw className="w-3.5 h-3.5" />
                                        Обновить
                                    </button>
                                </div>
                                <div className="space-y-2 max-h-[440px] overflow-y-auto pr-1">
                                    {sessions.length === 0 ? (
                                        <div className="text-white/40 text-sm">Сессий нет</div>
                                    ) : sessions.map((session) => (
                                        <div key={session.id} className="border border-white/10 rounded-xl bg-white/5 p-3 space-y-2">
                                            <div className="flex flex-wrap items-center gap-3 text-xs text-white/50">
                                                <span>ID: {session.id}</span>
                                                <span>Тип: {session.target_type || '—'}</span>
                                                <span>
                                                    Цель: {session.target_type === 'manual'
                                                        ? 'manual'
                                                        : (session.target_name || session.target_id || '—')}
                                                </span>
                                                <span>Начало: {formatDateTime(session.started_at)}</span>
                                                <span>Конец: {formatDateTime(session.ended_at)}</span>
                                                <span>Длительность: {session.duration_seconds ?? 0} сек.</span>
                                                <span>Баллы: {session.credited_points ?? 0}</span>
                                                {session.is_probation ? (
                                                    <span className="text-yellow-400/80 font-medium">Стажерский</span>
                                                ) : (
                                                    <span>Приоритет: {session.priority_override ?? session.priority_auto ?? 0}</span>
                                                )}
                                            </div>
                                            {editingSessionId === session.id && (
                                                <div className="space-y-3">
                                                    {/* Row 1: Target type + selector */}
                                                    <div className="flex flex-wrap items-center gap-2">
                                                        <div className="shrink-0 w-36">
                                                            <CustomDropdown
                                                                value={sessionEdit.target_type}
                                                                onChange={(v) => setSessionEdit((prev) => ({
                                                                    ...prev,
                                                                    target_type: v,
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
                                                            <div className="flex-1 min-w-[200px]">
                                                                <CustomSelect
                                                                    options={editTargetOptions}
                                                                    value={sessionEdit.target_id}
                                                                    onChange={(value) => {
                                                                        const targetId = String(value);
                                                                        const defaultPriority = sessionEdit.target_type === 'event'
                                                                            ? eventPriorityById[targetId] ?? 0
                                                                            : streamerPriorityById[targetId] ?? 0;
                                                                        setSessionEdit((prev) => ({
                                                                            ...prev,
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
                                                                onChange={(e) => setSessionEdit((prev) => ({ ...prev, target_name: e.target.value }))}
                                                                className="flex-1 min-w-[150px] bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
                                                                placeholder="Название"
                                                            />
                                                        )}
                                                    </div>
                                                    {/* Row 2: Date/time pickers */}
                                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                                        <div>
                                                            <label className="text-xs text-white/40 mb-1 block">Дата начала</label>
                                                            <CustomDatePicker
                                                                value={splitDateTime(sessionEdit.started_at).date}
                                                                onChange={(d) => setSessionEdit((prev) => ({ ...prev, started_at: mergeDateTimePart(prev.started_at, 'date', d) }))}
                                                                placeholder="Дата"
                                                            />
                                                        </div>
                                                        <div>
                                                            <label className="text-xs text-white/40 mb-1 block">Время начала</label>
                                                            <CustomTimePicker
                                                                value={splitDateTime(sessionEdit.started_at).time}
                                                                onChange={(t) => setSessionEdit((prev) => ({ ...prev, started_at: mergeDateTimePart(prev.started_at, 'time', t) }))}
                                                                placeholder="--:--"
                                                            />
                                                        </div>
                                                        <div>
                                                            <label className="text-xs text-white/40 mb-1 block">Дата конца</label>
                                                            <CustomDatePicker
                                                                value={splitDateTime(sessionEdit.ended_at).date}
                                                                onChange={(d) => setSessionEdit((prev) => ({ ...prev, ended_at: mergeDateTimePart(prev.ended_at, 'date', d) }))}
                                                                placeholder="Дата"
                                                            />
                                                        </div>
                                                        <div>
                                                            <label className="text-xs text-white/40 mb-1 block">Время конца</label>
                                                            <CustomTimePicker
                                                                value={splitDateTime(sessionEdit.ended_at).time}
                                                                onChange={(t) => setSessionEdit((prev) => ({ ...prev, ended_at: mergeDateTimePart(prev.ended_at, 'time', t) }))}
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
                                                                onChange={(e) => setSessionEdit((prev) => ({ ...prev, priority_override: e.target.value }))}
                                                                className="w-16 bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
                                                                disabled={sessionEdit.is_probation}
                                                            />
                                                        </div>
                                                        <label className="flex items-center gap-2 cursor-pointer group">
                                                            <div className="relative">
                                                                <input
                                                                    type="checkbox"
                                                                    className="sr-only peer"
                                                                    checked={sessionEdit.is_probation}
                                                                    onChange={(e) => setSessionEdit((prev) => ({ ...prev, is_probation: e.target.checked }))}
                                                                />
                                                                <div className="w-10 h-5 bg-white/10 rounded-full peer peer-checked:bg-yellow-500/50 transition-colors"></div>
                                                                <div className="absolute left-1 top-1 w-3 h-3 bg-white/40 rounded-full peer-checked:translate-x-5 peer-checked:bg-white transition-transform"></div>
                                                            </div>
                                                            <span className="text-xs text-white/60 group-hover:text-white transition-colors">Стажерский</span>
                                                        </label>
                                                    </div>
                                                </div>
                                            )}
                                            <div className="flex items-center gap-2">
                                                {editingSessionId === session.id ? (
                                                    <>
                                                        <button
                                                            onClick={() => void handleSessionPatch(session.id)}
                                                            disabled={busy}
                                                            className="text-xs px-3 py-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 disabled:opacity-50"
                                                        >
                                                            Сохранить
                                                        </button>
                                                        <button
                                                            onClick={() => setEditingSessionId(null)}
                                                            disabled={busy}
                                                            className="text-xs px-3 py-1.5 rounded-lg border border-white/20 bg-white/5 text-white/70 hover:bg-white/10 disabled:opacity-50"
                                                        >
                                                            Отмена
                                                        </button>
                                                    </>
                                                ) : (
                                                    <button
                                                        onClick={() => {
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
                                                                is_probation: !!session.is_probation,
                                                            });
                                                        }}
                                                        disabled={busy}
                                                        className="text-xs px-3 py-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 disabled:opacity-50"
                                                    >
                                                        Редактировать
                                                    </button>
                                                )}
                                                <button
                                                    onClick={() => void handleSessionDelete(session.id)}
                                                    disabled={busy}
                                                    className="text-xs px-3 py-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-red-300 hover:bg-red-500/20 disabled:opacity-50"
                                                >
                                                    Удалить
                                                </button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </>
                    )}
                </div>
            </div>

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
