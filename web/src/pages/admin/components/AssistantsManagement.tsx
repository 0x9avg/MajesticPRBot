import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, Check, Coins, RefreshCw, Shield, Timer, Trash2, Wrench } from 'lucide-react';
import { CustomSelect, CustomDatePicker, CustomTimePicker } from '../../../components/CustomInputs';
import type { Assistant, Event, Streamer } from '../../../types/domain';
import { unwrapApiData } from '../../../types/api';
import { parseMskDate, getMskNow, formatMskToLocal, formatToMskIso } from '../../../utils/datetime';

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

const formatDateTime = (value?: string | null) => {
    return formatMskToLocal(value);
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
    const [assistants, setAssistants] = useState<Assistant[]>([]);
    const [selectedPrId, setSelectedPrId] = useState<string | null>(null);
    const [selectedAssistant, setSelectedAssistant] = useState<Assistant | null>(null);
    const [sessions, setSessions] = useState<AssistantSessionRecord[]>([]);
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
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
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

    const [pointsForm, setPointsForm] = useState({ delta: '' });
    const [sanctionsForm, setSanctionsForm] = useState({ penalty_points: '', penalty_percent: '' });
    const [warningsForm, setWarningsForm] = useState({ target_state: '' });
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

    const getAccessToken = () => localStorage.getItem('access_token');

    const filteredAssistants = useMemo(() => {
        const query = search.trim().toLowerCase();
        if (!query) return assistants;
        return assistants.filter((assistant) =>
            assistant.nickname.toLowerCase().includes(query)
            || String(assistant.pr_id).includes(query)
        );
    }, [assistants, search]);

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

    const fetchAssistants = async () => {
        const response = await fetch('/api/assistants');
        if (!response.ok) throw new Error('Не удалось загрузить ассистентов');
        const json = await response.json() as unknown;
        const data = unwrapApiData<Assistant[] | { assistants: Assistant[] }>(json);
        const normalized = Array.isArray(data) ? data : data.assistants;
        const list = Array.isArray(normalized) ? normalized : [];
        setAssistants(list);
        if (list.length > 0) {
            setSelectedPrId((prev) => prev ?? String(list[0].pr_id));
        }
    };

    const fetchSessionTargetOptions = async () => {
        setOptionsLoading(true);
        setOptionsError(null);
        try {
            const [streamersResponse, eventsResponse] = await Promise.all([
                fetch('/api/streamers'),
                fetch('/api/events'),
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
    };

    const fetchAssistantDetail = async (prId: string) => {
        const response = await fetch(`/api/assistants/${prId}`);
        if (!response.ok) throw new Error('Не удалось загрузить профиль ассистента');
        const json = await response.json() as unknown;
        const data = unwrapApiData<Assistant>(json);
        setSelectedAssistant(data);
    };

    const fetchAssistantSessions = async (prId: string) => {
        const token = getAccessToken();
        if (!token) throw new Error('Требуется авторизация');

        const response = await fetch(`/api/assistants/${prId}/sessions?limit=50`, {
            headers: { Authorization: `Bearer ${token}` },
        });

        if (response.ok) {
            const json = await response.json() as unknown;
            const data = unwrapApiData<AssistantSessionRecord[]>(json);
            setSessions(Array.isArray(data) ? data : []);
            return;
        }

        // Fallback: if auth header is stripped somewhere in the chain,
        // still show read-only streamer sessions from public spec endpoint.
        if (response.status === 401 || response.status === 403) {
            const fallback = await fetch(`/api/spec/sessions/${prId}?limit=50`);
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
                setMessage({
                    type: 'error',
                    text: 'Сессии загружены в режиме read-only. Для админ-редактирования выполните повторный вход.',
                });
                return;
            }
        }

        throw new Error('Не удалось загрузить сессии ассистента');
    };

    const refreshSelectedAssistant = async (prId: string) => {
        const [detailResult, sessionsResult, assistantsResult] = await Promise.allSettled([
            fetchAssistantDetail(prId),
            fetchAssistantSessions(prId),
            fetchAssistants(),
        ]);

        if (detailResult.status === 'rejected') {
            throw detailResult.reason;
        }
        if (assistantsResult.status === 'rejected') {
            throw assistantsResult.reason;
        }
        if (sessionsResult.status === 'rejected') {
            setSessions([]);
            setMessage({
                type: 'error',
                text: sessionsResult.reason instanceof Error
                    ? sessionsResult.reason.message
                    : 'Не удалось загрузить сессии ассистента',
            });
        }
    };

    useEffect(() => {
        const load = async () => {
            try {
                setLoading(true);
                await Promise.all([fetchAssistants(), fetchSessionTargetOptions()]);
            } catch (error: unknown) {
                setMessage({ type: 'error', text: error instanceof Error ? error.message : 'Ошибка загрузки' });
            } finally {
                setLoading(false);
            }
        };
        void load();
    }, []);

    useEffect(() => {
        if (!selectedPrId) return;
        const loadSelected = async () => {
            try {
                setBusy(true);
                await refreshSelectedAssistant(selectedPrId);
            } catch (error: unknown) {
                setMessage({ type: 'error', text: error instanceof Error ? error.message : 'Ошибка загрузки данных ассистента' });
            } finally {
                setBusy(false);
            }
        };
        void loadSelected();
    }, [selectedPrId]);

    const runMutation = async (
        endpoint: string,
        method: 'POST' | 'PATCH' | 'DELETE',
        payload?: Record<string, unknown>,
    ) => {
        if (!selectedPrId) return;
        const token = getAccessToken();
        if (!token) throw new Error('Требуется авторизация');
        setBusy(true);
        setMessage(null);
        try {
            const response = await fetch(endpoint, {
                method,
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${token}`,
                },
                body: payload ? JSON.stringify(payload) : undefined,
            });
            const json = await response.json().catch(() => ({} as unknown));
            if (!response.ok) {
                throw new Error((json as { detail?: string }).detail || 'Операция не выполнена');
            }
            await refreshSelectedAssistant(selectedPrId);
            setMessage({ type: 'success', text: 'Изменения сохранены' });
        } finally {
            setBusy(false);
        }
    };

    const handlePointsAdjust = async () => {
        if (!selectedPrId) return;
        const delta = toNumberOrUndefined(pointsForm.delta);
        if (delta === undefined || delta === 0) {
            setMessage({ type: 'error', text: 'Укажите изменение баллов (не 0)' });
            return;
        }
        await runMutation(`/api/assistants/${selectedPrId}/points/adjust`, 'POST', {
            delta,
            source: 'manual_adjust',
        });
        setPointsForm({ delta: '' });
    };

    const handleSanctionsUpdate = async () => {
        if (!selectedPrId) return;
        const penaltyPoints = toNumberOrUndefined(sanctionsForm.penalty_points);
        const penaltyPercent = toNumberOrUndefined(sanctionsForm.penalty_percent);
        if (penaltyPoints === undefined && penaltyPercent === undefined) {
            setMessage({ type: 'error', text: 'Укажите хотя бы одно поле санкций' });
            return;
        }
        await runMutation(`/api/assistants/${selectedPrId}/sanctions`, 'PATCH', {
            penalty_points: penaltyPoints,
            penalty_percent: penaltyPercent,
        });
    };

    const handleWarningsUpdate = async () => {
        if (!selectedPrId || !selectedAssistant) return;
        if (!warningsForm.target_state) {
            setMessage({ type: 'error', text: 'Выберите итоговое состояние выговоров' });
            return;
        }

        const currentStrict = selectedAssistant.strict_warnings ?? 0;
        const currentOral = selectedAssistant.oral_warnings ?? 0;

        const [strictStr, oralStr] = warningsForm.target_state.split('-');
        const targetStrict = parseInt(strictStr, 10);
        const targetOral = parseInt(oralStr, 10);

        const strictDelta = targetStrict - currentStrict;
        const oralDelta = targetOral - currentOral;

        if (strictDelta === 0 && oralDelta === 0) {
            setMessage({ type: 'error', text: 'Состояние не изменилось (дельта 0)' });
            return;
        }

        await runMutation(`/api/assistants/${selectedPrId}/warnings`, 'POST', {
            oral_delta: oralDelta,
            strict_delta: strictDelta,
        });
        setWarningsForm({ target_state: '' });
    };

    const handleManualSessionCreate = async () => {
        if (!selectedPrId) return;
        const startedAtIso = parseLocalDateTimeToIso(manualSessionForm.started_at);
        const endedAtIso = parseLocalDateTimeToIso(manualSessionForm.ended_at);
        if (!startedAtIso || !endedAtIso) {
            setMessage({ type: 'error', text: 'Укажите корректные начало и конец сессии' });
            return;
        }
        if (new Date(endedAtIso).getTime() <= new Date(startedAtIso).getTime()) {
            setMessage({ type: 'error', text: 'Конец сессии должен быть позже начала' });
            return;
        }
        const targetType = manualSessionForm.target_type;
        const targetOptions = targetType === 'event' ? eventOptions : streamerOptions;
        if (targetType !== 'manual' && !canUseStreamerOrEventSelectors) {
            setMessage({ type: 'error', text: optionsError || 'Справочники стримеров/событий пока недоступны' });
            return;
        }
        if (targetType !== 'manual' && targetOptions.length === 0) {
            setMessage({ type: 'error', text: targetType === 'event' ? 'Нет доступных событий' : 'Нет доступных стримеров' });
            return;
        }
        if (manualSessionForm.target_type !== 'manual' && !manualSessionForm.target_id.trim()) {
            setMessage({ type: 'error', text: 'Выберите цель спека' });
            return;
        }
        const parsedTargetId = toNumberOrUndefined(manualSessionForm.target_id);
        if (manualSessionForm.target_type !== 'manual' && parsedTargetId === undefined) {
            setMessage({ type: 'error', text: 'Некорректная цель спека' });
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
            setMessage({ type: 'error', text: 'Укажите корректные начало и конец сессии' });
            return;
        }
        if (new Date(endedAtIso).getTime() <= new Date(startedAtIso).getTime()) {
            setMessage({ type: 'error', text: 'Конец сессии должен быть позже начала' });
            return;
        }
        const targetType = sessionEdit.target_type;
        const targetOptions = targetType === 'event' ? eventOptions : streamerOptions;
        if (targetType !== 'manual' && !canUseStreamerOrEventSelectors) {
            setMessage({ type: 'error', text: optionsError || 'Справочники стримеров/событий пока недоступны' });
            return;
        }
        if (targetType !== 'manual' && targetOptions.length === 0) {
            setMessage({ type: 'error', text: targetType === 'event' ? 'Нет доступных событий' : 'Нет доступных стримеров' });
            return;
        }
        if (sessionEdit.target_type !== 'manual' && !sessionEdit.target_id.trim()) {
            setMessage({ type: 'error', text: 'Выберите цель спека' });
            return;
        }
        const parsedTargetId = toNumberOrUndefined(sessionEdit.target_id);
        if (sessionEdit.target_type !== 'manual' && parsedTargetId === undefined) {
            setMessage({ type: 'error', text: 'Некорректная цель спека' });
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
        setMessage(null);
        try {
            const token = getAccessToken();
            if (!token) throw new Error('Требуется авторизация');
            const response = await fetch('/api/assistants', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${token}`,
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
            setMessage({ type: 'success', text: `Роль изменена на ${newRole}` });
        } catch (error: unknown) {
            setMessage({ type: 'error', text: error instanceof Error ? error.message : 'Ошибка смены роли' });
        } finally {
            setBusy(false);
        }
    };

    const handleDeleteAssistant = async () => {
        if (!selectedPrId || !selectedAssistant) return;
        const confirmed = window.confirm(`Удалить ассистента ${selectedAssistant.nickname}? Это действие нельзя отменить.`);
        if (!confirmed) return;
        setBusy(true);
        setMessage(null);
        try {
            const token = getAccessToken();
            if (!token) throw new Error('Требуется авторизация');
            const response = await fetch(`/api/assistants/${selectedPrId}`, {
                method: 'DELETE',
                headers: { Authorization: `Bearer ${token}` },
            });
            if (!response.ok) {
                const json = await response.json().catch(() => ({} as unknown));
                throw new Error((json as { detail?: string }).detail || 'Не удалось удалить ассистента');
            }
            setSelectedPrId(null);
            setSelectedAssistant(null);
            setSessions([]);
            await fetchAssistants();
            setMessage({ type: 'success', text: `Ассистент удален` });
        } catch (error: unknown) {
            setMessage({ type: 'error', text: error instanceof Error ? error.message : 'Ошибка удаления ассистента' });
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
                    <p className="text-white/60">Управление баллами, санкциями, выговорами и сессиями</p>
                </div>
            </div>

            {message && (
                <div className={`px-4 py-3 rounded-xl flex items-center gap-3 ${message.type === 'success' ? 'bg-green-500/10 border border-green-500/20 text-green-300' : 'bg-red-500/10 border border-red-500/20 text-red-300'}`}>
                    {message.type === 'success' ? <Check className="w-5 h-5" /> : <AlertCircle className="w-5 h-5" />}
                    {message.text}
                </div>
            )}

            {optionsError && (
                <div className="px-4 py-3 rounded-xl flex items-center gap-3 bg-yellow-500/10 border border-yellow-500/20 text-yellow-200">
                    <AlertCircle className="w-5 h-5" />
                    {optionsError}. Для `manual`-спека форма продолжит работать.
                </div>
            )}

            <div className="grid grid-cols-1 xl:grid-cols-4 gap-4">
                <div className="xl:col-span-1 bg-[#1e1e1e] border border-white/5 rounded-2xl p-4 space-y-3">
                    <input
                        type="text"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder="Поиск: ник или PR ID"
                        className="w-full bg-[#2a2a2a] border border-white/10 rounded-xl px-3 py-2 text-sm text-white"
                    />
                    <div className="max-h-[520px] overflow-y-auto space-y-2 pr-1">
                        {loading ? (
                            <div className="text-white/50 text-sm">Загрузка...</div>
                        ) : filteredAssistants.length === 0 ? (
                            <div className="text-white/40 text-sm">Ничего не найдено</div>
                        ) : (
                            filteredAssistants.map((assistant) => (
                                <button
                                    key={assistant.pr_id}
                                    onClick={() => setSelectedPrId(String(assistant.pr_id))}
                                    className={`w-full text-left rounded-xl border px-3 py-2 transition-colors ${String(assistant.pr_id) === selectedPrId ? 'border-indigo-400/40 bg-indigo-500/10 text-indigo-200' : 'border-white/10 bg-white/5 text-white/80 hover:bg-white/10'}`}
                                >
                                    <div className="font-medium truncate">{assistant.nickname}</div>
                                    <div className="text-xs text-white/50">PR ID: {assistant.pr_id}</div>
                                </button>
                            ))
                        )}
                    </div>
                </div>

                <div className="xl:col-span-3 space-y-4">
                    {!selectedAssistant ? (
                        <div className="bg-[#1e1e1e] border border-white/5 rounded-2xl p-8 text-white/50 text-center">
                            Выберите ассистента для управления
                        </div>
                    ) : (
                        <>
                            <div className="bg-[#1e1e1e] border border-white/5 rounded-2xl p-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3">
                                <div className="bg-white/5 rounded-xl p-3">
                                    <div className="text-xs text-white/50">Ник</div>
                                    <div className="text-white font-semibold">{selectedAssistant.nickname}</div>
                                </div>
                                <div className="bg-white/5 rounded-xl p-3">
                                    <div className="text-xs text-white/50">Баллы</div>
                                    <div className="text-green-300 font-semibold">{selectedAssistant.total_points ?? 0}</div>
                                </div>
                                <div className="bg-white/5 rounded-xl p-3">
                                    <div className="text-xs text-white/50">Штрафные баллы</div>
                                    <div className="text-amber-300 font-semibold">{selectedAssistant.penalty_points ?? 0}</div>
                                </div>
                                <div className="bg-white/5 rounded-xl p-3">
                                    <div className="text-xs text-white/50">Штраф, %</div>
                                    <div className="text-amber-300 font-semibold">{selectedAssistant.penalty_percent ?? 0}%</div>
                                </div>
                                <div className="bg-white/5 rounded-xl p-3">
                                    <div className="text-xs text-white/50">Выговоры</div>
                                    <div className="text-white font-semibold">{selectedAssistant.warnings_display ?? '0/2 0/2'}</div>
                                </div>
                            </div>

                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                                <div className="bg-[#1e1e1e] border border-white/5 rounded-2xl p-4 space-y-3">
                                    <div className="text-white font-semibold flex items-center gap-2">
                                        <Coins className="w-4 h-4 text-green-400" />Баллы
                                    </div>
                                    <div className="relative">
                                        <input
                                            type="number"
                                            step="0.0001"
                                            value={pointsForm.delta}
                                            onChange={(e) => setPointsForm((prev) => ({ ...prev, delta: e.target.value }))}
                                            className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg pl-3 pr-24 py-2 text-sm text-white focus:outline-none focus:border-white/20"
                                            placeholder="Изменение баллов (дельта)"
                                        />
                                        {pointsForm.delta && !isNaN(Number(pointsForm.delta)) && (
                                            <div className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-semibold px-2 py-0.5 rounded-md bg-white/10 text-white/90 shadow-sm border border-white/5 pointer-events-none">
                                                Итог: {(Number(selectedAssistant.total_points ?? 0) + Number(pointsForm.delta)).toFixed(2).replace(/\.00$/, '')}
                                            </div>
                                        )}
                                    </div>
                                    <button
                                        onClick={() => void handlePointsAdjust()}
                                        disabled={busy}
                                        className="w-full rounded-lg px-3 py-2 text-sm font-medium bg-blue-500/20 text-blue-300 hover:bg-blue-500/30 disabled:opacity-50"
                                    >
                                        Применить изменение
                                    </button>
                                </div>

                                <div className="bg-[#1e1e1e] border border-white/5 rounded-2xl p-4 space-y-3">
                                    <div className="text-white font-semibold flex items-center gap-2"><Shield className="w-4 h-4 text-amber-400" />Санкции и выговоры</div>
                                    <div className="grid grid-cols-2 gap-2">
                                        <div className="relative">
                                            <input
                                                type="number"
                                                step="0.0001"
                                                min="0"
                                                value={sanctionsForm.penalty_points}
                                                onChange={(e) => setSanctionsForm((prev) => ({ ...prev, penalty_points: e.target.value }))}
                                                className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg pl-3 pr-20 py-2 text-sm text-white"
                                                placeholder="± Баллы"
                                            />
                                            {sanctionsForm.penalty_points && !isNaN(Number(sanctionsForm.penalty_points)) && (
                                                <div className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] font-semibold px-1.5 py-0.5 rounded-md bg-white/10 text-white/90 shadow-sm border border-white/5 pointer-events-none">
                                                    Итог: {Math.max(0, Number(selectedAssistant.penalty_points ?? 0) + Number(sanctionsForm.penalty_points)).toFixed(2).replace(/\.00$/, '')}
                                                </div>
                                            )}
                                        </div>
                                        <div className="relative">
                                            <input
                                                type="number"
                                                step="0.01"
                                                min="0"
                                                value={sanctionsForm.penalty_percent}
                                                onChange={(e) => setSanctionsForm((prev) => ({ ...prev, penalty_percent: e.target.value }))}
                                                className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg pl-3 pr-20 py-2 text-sm text-white"
                                                placeholder="± Проценты"
                                            />
                                            {sanctionsForm.penalty_percent && !isNaN(Number(sanctionsForm.penalty_percent)) && (
                                                <div className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] font-semibold px-1.5 py-0.5 rounded-md bg-white/10 text-white/90 shadow-sm border border-white/5 pointer-events-none">
                                                    Итог: {Math.max(0, Number(selectedAssistant.penalty_percent ?? 0) + Number(sanctionsForm.penalty_percent)).toFixed(2).replace(/\.00$/, '')}%
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                    <button
                                        onClick={() => void handleSanctionsUpdate()}
                                        disabled={busy}
                                        className="w-full rounded-lg px-3 py-2 text-sm font-medium bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 disabled:opacity-50 mb-2"
                                    >
                                        Обновить штрафы
                                    </button>

                                    <div className="pt-2 border-t border-white/10">
                                        <select
                                            value={warningsForm.target_state}
                                            onChange={(e) => setWarningsForm((prev) => ({ ...prev, target_state: e.target.value }))}
                                            className={`w-full bg-[#2a2a2a] border border-white/10 rounded-lg px-3 py-2 text-sm font-semibold outline-none focus:border-white/30 mb-2 cursor-pointer transition-colors ${warningsForm.target_state === '0-0' ? 'text-green-400' :
                                                warningsForm.target_state === '0-1' ? 'text-yellow-400' :
                                                    warningsForm.target_state === '1-0' ? 'text-orange-400' :
                                                        warningsForm.target_state === '1-1' ? 'text-red-400' :
                                                            'text-white/60'
                                                }`}
                                        >
                                            <option value="" disabled className="text-white/60 font-normal">Выберите состояние выговоров</option>
                                            <option value="0-0" className="text-green-400 font-semibold bg-[#2a2a2a]">🟢 [0/2][0/2] — Нет выговоров</option>
                                            <option value="0-1" className="text-yellow-400 font-semibold bg-[#2a2a2a]">🟡 [0/2][1/2] — 1 Устный</option>
                                            <option value="1-0" className="text-orange-400 font-semibold bg-[#2a2a2a]">🟠 [1/2][0/2] — 1 Строгий</option>
                                            <option value="1-1" className="text-red-400 font-semibold bg-[#2a2a2a]">🔴 [1/2][1/2] — 1 Строгий, 1 Устный</option>
                                        </select>

                                        <button
                                            onClick={() => void handleWarningsUpdate()}
                                            disabled={busy || !warningsForm.target_state}
                                            className="w-full rounded-lg px-3 py-2 text-sm font-medium bg-fuchsia-500/20 text-fuchsia-300 hover:bg-fuchsia-500/30 disabled:opacity-50"
                                        >
                                            Обновить выговоры
                                        </button>
                                    </div>
                                </div>
                            </div>


                            {/* Role & Delete */}
                            <div className="bg-[#1e1e1e] border border-white/5 rounded-2xl p-4 flex items-center gap-4">
                                <div className="flex-1">
                                    <label className="text-xs text-white/50 mb-1 block">Роль</label>
                                    <select
                                        value={selectedAssistant.role || 'employee'}
                                        onChange={(e) => void handleRoleChange(e.target.value)}
                                        disabled={busy}
                                        className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg px-3 py-2 text-sm text-white disabled:opacity-50"
                                    >
                                        <option value="junior_employee">Стажер</option>
                                        <option value="employee">Сотрудник</option>
                                        <option value="senior_employee">Старший сотрудник</option>
                                        <option value="manager">Менеджер</option>
                                        <option value="developer">Разработчик</option>
                                    </select>
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


                            <div className="bg-[#1e1e1e] border border-white/5 rounded-2xl p-4 space-y-3">
                                <div className="flex items-center justify-between">
                                    <div className="text-white font-semibold flex items-center gap-2"><Timer className="w-4 h-4 text-indigo-400" />Ручная сессия</div>

                                </div>
                                <div className="space-y-3">
                                    {/* Row 1: Target type + selector */}
                                    <div className="flex flex-wrap items-center gap-2">
                                        <select
                                            value={manualSessionForm.target_type}
                                            onChange={(e) => setManualSessionForm((prev) => ({
                                                ...prev,
                                                target_type: e.target.value,
                                                target_id: '',
                                                priority: '0',
                                            }))}
                                            className="bg-[#2a2a2a] border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
                                        >
                                            <option value="streamer">Стример</option>
                                            <option value="event">Событие</option>
                                            <option value="manual">Manual</option>
                                        </select>
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
                                                className="flex-1 min-w-[150px] bg-[#2a2a2a] border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
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
                                                className="w-16 bg-[#2a2a2a] border border-white/10 rounded-lg px-3 py-2 text-sm text-white disabled:opacity-50"
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

                            <div className="bg-[#1e1e1e] border border-white/5 rounded-2xl p-4 space-y-3">
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
                                                        <select
                                                            value={sessionEdit.target_type}
                                                            onChange={(e) => setSessionEdit((prev) => ({
                                                                ...prev,
                                                                target_type: e.target.value,
                                                                target_id: '',
                                                                priority_override: '0',
                                                            }))}
                                                            className="bg-[#2a2a2a] border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
                                                        >
                                                            <option value="streamer">Стример</option>
                                                            <option value="event">Событие</option>
                                                            <option value="manual">Manual</option>
                                                        </select>
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
                                                                className="flex-1 min-w-[150px] bg-[#2a2a2a] border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
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
                                                                className="w-16 bg-[#2a2a2a] border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
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
        </div>
    );
};

export default AssistantsManagement;
