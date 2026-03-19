import React from 'react';
import {
    CalendarClock,
    CheckCircle2,
    ClipboardCopy,
    RefreshCw,
    Search,
    UserRound,
} from 'lucide-react';

import { apiFetch } from '../../../api/client';
import NotificationToast from '../../../components/feedback/NotificationToast';
import { usePopupToast } from '../../../components/feedback/hooks';
import { getApiErrorMessage, unwrapApiData } from '../../../types/api';
import type {
    WeeklyAdminListResponse,
    WeeklyAssistantDetail,
    WeeklyAssistantSummary,
    WeeklyDayStatus,
    WeeklyPayoutIssueStatus,
    WeeklyPayoutServer,
    WeeklyPayoutType,
    WeeklySelectedResult,
    WeeklySuggestedResult,
} from '../../../types/domain';
import { formatMskToLocal, formatToMskIso, getMskTodayStr, parseMskDate } from '../../../utils/datetime';

type WeeklyDraftRow = WeeklyAssistantDetail;
type EditableWeeklyField = 'selected_result' | 'payout_type' | 'payout_server' | 'payout_static';
type WeeklyFilterMode = 'all' | 'status_marks' | 'no_result' | 'drafts' | 'ready_issue' | 'issued';
type WeeklyDayControlValue = 'inherit' | 'clear' | WeeklyDayStatus;
type WeeklyPayoutDisplayState = 'not_ready' | 'ready' | 'issued';

const WEEKDAY_LABELS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

const FALLBACK_RESULT_OPTIONS: WeeklySelectedResult[] = [
    'Ультра-Актив',
    'Актив',
    'Актив/Отпуск',
    'Инактив',
    'Инактив/Отпуск',
    'Отпуск',
    'Инактив/Актив',
];

const FALLBACK_PAYOUT_TYPES: Array<{ value: WeeklyPayoutType; label: string }> = [
    { value: 'EXP', label: 'EXP' },
    { value: 'Premium', label: 'Premium' },
    { value: 'MC', label: 'MC' },
    { value: 'MONEY', label: 'MONEY' },
];

const FALLBACK_PAYOUT_SERVERS: WeeklyPayoutServer[] = Array.from({ length: 18 }, (_value, index) => `RU${index + 1}`);

const getRoleLabel = (role: string) => {
    switch (role) {
        case 'developer':
            return 'Разработчик';
        case 'manager':
            return 'Глав. ассистент';
        case 'senior_employee':
            return 'Ст. ассистент';
        case 'employee':
            return 'Ассистент';
        case 'junior_employee':
            return 'Мл. ассистент';
        default:
            return role;
    }
};

const getRoleTone = (role: string) => {
    switch (role) {
        case 'developer':
            return 'border-red-500/30 bg-red-500/15 text-red-200';
        case 'manager':
            return 'border-orange-500/30 bg-orange-500/15 text-orange-200';
        case 'senior_employee':
            return 'border-blue-500/30 bg-blue-500/15 text-blue-200';
        case 'employee':
            return 'border-slate-500/30 bg-slate-500/15 text-slate-200';
        case 'junior_employee':
            return 'border-zinc-500/30 bg-zinc-500/15 text-zinc-200';
        default:
            return 'border-white/10 bg-white/5 text-white/60';
    }
};

const getStatusLabel = (value: WeeklyDayStatus | null | undefined) => {
    switch (value) {
        case 'P':
            return 'П';
        case 'U':
            return 'У';
        case 'O':
            return 'О';
        default:
            return '—';
    }
};

const getStatusTone = (value: WeeklyDayStatus | null | undefined) => {
    switch (value) {
        case 'P':
            return 'bg-rose-500/15 text-rose-200 border-rose-500/30';
        case 'U':
            return 'bg-sky-500/15 text-sky-200 border-sky-500/30';
        case 'O':
            return 'bg-amber-500/15 text-amber-200 border-amber-500/30';
        default:
            return 'bg-white/5 text-white/50 border-white/10';
    }
};

const getResultTone = (value: WeeklySelectedResult | WeeklySuggestedResult | null | undefined) => {
    switch (value) {
        case 'Ультра-Актив':
            return 'bg-fuchsia-500/15 text-fuchsia-200 border-fuchsia-500/30';
        case 'Актив':
            return 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30';
        case 'Актив/Отпуск':
            return 'bg-cyan-500/15 text-cyan-200 border-cyan-500/30';
        case 'Инактив/Актив':
            return 'bg-amber-500/15 text-amber-200 border-amber-500/30';
        case 'Инактив/Отпуск':
            return 'bg-orange-500/15 text-orange-200 border-orange-500/30';
        case 'Отпуск':
            return 'bg-violet-500/15 text-violet-200 border-violet-500/30';
        case 'Инактив':
            return 'bg-rose-500/15 text-rose-200 border-rose-500/30';
        default:
            return 'bg-white/5 text-white/50 border-white/10';
    }
};

const normalizeWeekStart = (value?: string | null) => {
    const parsed = parseMskDate(value ?? getMskTodayStr());
    if (!parsed) return getMskTodayStr();
    const weekday = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Europe/Moscow',
        weekday: 'short',
    }).format(parsed);
    const offsetByWeekday: Record<string, number> = {
        Mon: 0,
        Tue: 1,
        Wed: 2,
        Thu: 3,
        Fri: 4,
        Sat: 5,
        Sun: 6,
    };
    const offset = offsetByWeekday[weekday] ?? 0;
    parsed.setUTCDate(parsed.getUTCDate() - offset);
    return formatToMskIso(parsed).slice(0, 10);
};

const addDays = (date: string, days: number) => {
    const parsed = parseMskDate(date);
    if (!parsed) return date;
    parsed.setUTCDate(parsed.getUTCDate() + days);
    return formatToMskIso(parsed).slice(0, 10);
};

const buildWeekDays = (weekStart: string) => Array.from({ length: 7 }, (_value, index) => {
    const workDate = addDays(weekStart, index);
    return {
        work_date: workDate,
        label: WEEKDAY_LABELS[index],
        short_date: formatMskToLocal(workDate, { day: '2-digit', month: '2-digit' }),
    };
});

const formatWeekRange = (weekStart: string, weekEnd: string) => {
    const start = formatMskToLocal(weekStart, { day: '2-digit', month: '2-digit' });
    const end = formatMskToLocal(weekEnd, { day: '2-digit', month: '2-digit' });
    return `${start} - ${end}`;
};

const formatHours = (value: number) => {
    const rounded = Number(value ?? 0);
    if (!Number.isFinite(rounded)) return '0ч';
    return `${rounded.toFixed(1).replace(/\.0$/, '')}ч`;
};

const sortPayoutServers = (servers: WeeklyPayoutServer[]) => (
    [...servers].sort((left, right) => left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' }))
);

const getPayoutStatusMeta = (state: WeeklyPayoutDisplayState) => {
    switch (state) {
        case 'issued':
            return {
                label: 'Выдано',
                tone: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100',
            };
        case 'ready':
            return {
                label: 'Готово к выдаче',
                tone: 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100',
            };
        default:
            return {
                label: 'Не готово',
                tone: 'border-white/10 bg-white/5 text-white/45',
            };
    }
};

const getDayControlValue = (day: WeeklyDraftRow['days'][number]): WeeklyDayControlValue => {
    if (day.status_source === 'manual') {
        return day.manual_status ?? 'clear';
    }
    return 'inherit';
};

const getDayControlOptions = (day: WeeklyDraftRow['days'][number]) => {
    const options: Array<{ value: WeeklyDayControlValue; label: string }> = [
        {
            value: 'inherit',
            label: day.auto_status ? `Авто: ${getStatusLabel(day.auto_status)}` : '—',
        },
    ];
    if (day.auto_status) {
        options.push({ value: 'clear', label: 'Без статуса' });
    }
    options.push(
        { value: 'P', label: 'П' },
        { value: 'U', label: 'У' },
        { value: 'O', label: 'О' },
    );
    return options;
};

const cloneDraft = (assistant: WeeklyAssistantSummary | WeeklyAssistantDetail): WeeklyDraftRow => ({
    ...assistant,
    payout_issue_status: assistant.payout_issue_status ?? 'pending',
    payout_issued_at: assistant.payout_issued_at ?? null,
    payout_issued_by_id: assistant.payout_issued_by_id ?? null,
    days: assistant.days.map((day) => ({
        ...day,
        manual_status: day.manual_status ?? null,
        auto_status: day.auto_status ?? null,
        resolved_status: day.resolved_status ?? null,
        status_source: day.status_source ?? 'none',
    })),
    day_overrides: assistant.days.map((day) => ({
        work_date: day.work_date,
        manual_status: day.manual_status ?? null,
        is_manual_override: (day.status_source ?? 'none') === 'manual',
    })),
});

const recomputeCounts = (draft: WeeklyDraftRow): WeeklyDraftRow => {
    let countP = 0;
    let countU = 0;
    let countO = 0;

    draft.days.forEach((day) => {
        if (day.resolved_status === 'P') countP += 1;
        if (day.resolved_status === 'U') countU += 1;
        if (day.resolved_status === 'O') countO += 1;
    });

    return {
        ...draft,
        count_P: countP,
        count_U: countU,
        count_O: countO,
        result_display: draft.selected_result ?? draft.suggested_result,
        day_overrides: draft.days.map((day) => ({
            work_date: day.work_date,
            manual_status: day.manual_status ?? null,
            is_manual_override: day.status_source === 'manual',
        })),
    };
};

const areManualOverridesEqual = (left: WeeklyDraftRow, right: WeeklyDraftRow) => left.days.every((day, index) => {
    const other = right.days[index];
    return day.work_date === other?.work_date
        && (day.manual_status ?? null) === (other?.manual_status ?? null)
        && day.status_source === other?.status_source;
});

const isRowDirty = (base: WeeklyAssistantSummary | undefined, draft: WeeklyDraftRow) => {
    if (!base) return false;
    return !areManualOverridesEqual(cloneDraft(base), draft)
        || (base.selected_result ?? null) !== (draft.selected_result ?? null)
        || (base.payout_type ?? null) !== (draft.payout_type ?? null)
        || (base.payout_server ?? null) !== (draft.payout_server ?? null)
        || (base.payout_static ?? null) !== (draft.payout_static ?? null);
};

const areCommandInputsDirty = (base: WeeklyAssistantSummary | undefined, draft: WeeklyDraftRow) => {
    if (!base) return false;
    return (base.selected_result ?? null) !== (draft.selected_result ?? null)
        || (base.payout_type ?? null) !== (draft.payout_type ?? null)
        || (base.payout_server ?? null) !== (draft.payout_server ?? null)
        || (base.payout_static ?? null) !== (draft.payout_static ?? null);
};

const getCommandState = (base: WeeklyAssistantSummary | undefined, draft: WeeklyDraftRow) => {
    if (areCommandInputsDirty(base, draft)) {
        return {
            available: false,
            command: null as string | null,
            reason: 'Сохрани изменения для генерации команды',
        };
    }

    return {
        available: Boolean(draft.generated_payout_available && draft.generated_payout_command),
        command: draft.generated_payout_command ?? null,
        reason: draft.generated_payout_command ? null : (draft.generated_payout_reason ?? 'Команда пока недоступна'),
    };
};

const needsDecision = (row: WeeklyDraftRow) => !row.selected_result;

const getPayoutDisplayState = (row: WeeklyDraftRow, base: WeeklyAssistantSummary | undefined): WeeklyPayoutDisplayState => {
    if (row.payout_issue_status === 'issued') {
        return 'issued';
    }
    const commandState = getCommandState(base, row);
    if (commandState.available && !isRowDirty(base, row)) {
        return 'ready';
    }
    return 'not_ready';
};

const isReadyForIssue = (row: WeeklyDraftRow, base: WeeklyAssistantSummary | undefined) => (
    getPayoutDisplayState(row, base) === 'ready'
);
const isIssuedPayout = (row: WeeklyDraftRow) => row.payout_issue_status === 'issued';
const hasWeeklyMarks = (row: WeeklyDraftRow) => row.count_P > 0 || row.count_U > 0 || row.count_O > 0;
const isDraftReview = (row: WeeklyDraftRow, base: WeeklyAssistantSummary | undefined) => isRowDirty(base, row);

const matchesFilterMode = (
    mode: WeeklyFilterMode,
    row: WeeklyDraftRow,
    base: WeeklyAssistantSummary | undefined,
) => {
    switch (mode) {
        case 'status_marks':
            return hasWeeklyMarks(row);
        case 'no_result':
            return needsDecision(row);
        case 'drafts':
            return isDraftReview(row, base);
        case 'ready_issue':
            return isReadyForIssue(row, base);
        case 'issued':
            return isIssuedPayout(row);
        default:
            return true;
    }
};

const AssistantWeeklyStatsManagement = () => {
    const { toast, showToast, closeToast } = usePopupToast(3200);
    const [adminWeek, setAdminWeek] = React.useState<WeeklyAdminListResponse | null>(null);
    const [loading, setLoading] = React.useState(true);
    const [weekStart, setWeekStart] = React.useState(() => normalizeWeekStart(getMskTodayStr()));
    const [search, setSearch] = React.useState('');
    const [filterMode, setFilterMode] = React.useState<WeeklyFilterMode>('all');
    const [rowDrafts, setRowDrafts] = React.useState<Record<string, WeeklyDraftRow>>({});
    const [savingRows, setSavingRows] = React.useState<Record<string, boolean>>({});
    const [issuingRows, setIssuingRows] = React.useState<Record<string, boolean>>({});
    const [rowErrors, setRowErrors] = React.useState<Record<string, string | null>>({});

    const loadAdmin = React.useCallback(async (targetWeek = weekStart) => {
        setLoading(true);
        try {
            const response = await apiFetch(`/api/assistant-weekly/admin?week_start=${targetWeek}`);
            const data = await response.json().catch(() => ({} as unknown));
            if (!response.ok) {
                throw new Error(getApiErrorMessage(data, 'Не удалось загрузить недельную статистику'));
            }

            const payload = unwrapApiData<WeeklyAdminListResponse>(data);
            setAdminWeek(payload);
            setRowDrafts(
                Object.fromEntries(
                    payload.items.map((item) => [item.assistant_id, recomputeCounts(cloneDraft(item))]),
                ),
            );
            setSavingRows({});
            setIssuingRows({});
            setRowErrors({});
        } catch (error: unknown) {
            showToast(error instanceof Error ? error.message : 'Не удалось загрузить недельную статистику', 'error');
        } finally {
            setLoading(false);
        }
    }, [showToast, weekStart]);

    React.useEffect(() => {
        void loadAdmin(weekStart);
    }, [loadAdmin, weekStart]);

    const headerDays = React.useMemo(() => {
        if (adminWeek?.day_labels?.length) {
            return adminWeek.day_labels.map((day, index) => ({
                work_date: day.work_date,
                label: day.label || WEEKDAY_LABELS[index],
                short_date: formatMskToLocal(day.work_date, { day: '2-digit', month: '2-digit' }),
            }));
        }
        return buildWeekDays(weekStart);
    }, [adminWeek?.day_labels, weekStart]);

    const payoutServers = React.useMemo(
        () => sortPayoutServers(adminWeek?.payout_servers?.length ? adminWeek.payout_servers : FALLBACK_PAYOUT_SERVERS),
        [adminWeek?.payout_servers],
    );

    const baseRowsById = React.useMemo(
        () => Object.fromEntries((adminWeek?.items ?? []).map((item) => [item.assistant_id, item])),
        [adminWeek?.items],
    );

    const tableRows = React.useMemo(
        () => (adminWeek?.items ?? []).map((item) => rowDrafts[item.assistant_id] ?? recomputeCounts(cloneDraft(item))),
        [adminWeek?.items, rowDrafts],
    );

    const filteredRows = React.useMemo(() => {
        const query = search.trim().toLowerCase();
        return tableRows.filter((row) => {
            const baseRow = baseRowsById[row.assistant_id];
            const textMatch = !query
                || row.nickname.toLowerCase().includes(query)
                || getRoleLabel(row.role).toLowerCase().includes(query);
            return textMatch && matchesFilterMode(filterMode, row, baseRow);
        });
    }, [baseRowsById, filterMode, search, tableRows]);

    const summary = React.useMemo(() => ({
        total: tableRows.length,
        withStatusMarks: tableRows.filter((row) => hasWeeklyMarks(row)).length,
        withoutResult: tableRows.filter((row) => needsDecision(row)).length,
        drafts: tableRows.filter((row) => isDraftReview(row, baseRowsById[row.assistant_id])).length,
        readyIssue: tableRows.filter((row) => isReadyForIssue(row, baseRowsById[row.assistant_id])).length,
        issued: tableRows.filter((row) => isIssuedPayout(row)).length,
    }), [baseRowsById, tableRows]);

    const summaryCards = React.useMemo(() => ([
        {
            mode: 'all' as const,
            label: 'Все',
            count: summary.total,
            tone: 'border-white/10 bg-white/[0.03] text-white',
        },
        {
            mode: 'status_marks' as const,
            label: 'Есть П / У / О',
            count: summary.withStatusMarks,
            tone: 'border-sky-500/15 bg-sky-500/[0.05] text-sky-100',
        },
        {
            mode: 'no_result' as const,
            label: 'Без итогового решения',
            count: summary.withoutResult,
            tone: 'border-amber-500/15 bg-amber-500/[0.05] text-amber-50',
        },
        {
            mode: 'drafts' as const,
            label: 'Черновики',
            count: summary.drafts,
            tone: 'border-fuchsia-500/15 bg-fuchsia-500/[0.05] text-fuchsia-50',
        },
        {
            mode: 'ready_issue' as const,
            label: 'Готово к выдаче',
            count: summary.readyIssue,
            tone: 'border-cyan-500/15 bg-cyan-500/[0.05] text-cyan-50',
        },
        {
            mode: 'issued' as const,
            label: 'Выдано',
            count: summary.issued,
            tone: 'border-emerald-500/15 bg-emerald-500/[0.05] text-emerald-50',
        },
    ]), [summary]);

    const updateRowDraft = (assistantId: string, updater: (draft: WeeklyDraftRow) => WeeklyDraftRow) => {
        setRowDrafts((current) => {
            const draft = current[assistantId];
            if (!draft) return current;
            return {
                ...current,
                [assistantId]: recomputeCounts(updater(draft)),
            };
        });
        setRowErrors((current) => ({
            ...current,
            [assistantId]: null,
        }));
    };

    const updateRowDayStatus = (assistantId: string, workDate: string, value: WeeklyDayControlValue) => {
        updateRowDraft(assistantId, (draft) => ({
            ...draft,
            days: draft.days.map((day) => {
                if (day.work_date !== workDate) return day;
                if (value === 'inherit') {
                    return {
                        ...day,
                        manual_status: null,
                        resolved_status: day.auto_status ?? null,
                        status_source: day.auto_status ? 'auto' : 'none',
                    };
                }
                if (value === 'clear') {
                    return {
                        ...day,
                        manual_status: null,
                        resolved_status: null,
                        status_source: 'manual',
                    };
                }
                return {
                    ...day,
                    manual_status: value,
                    resolved_status: value,
                    status_source: 'manual',
                };
            }),
        }));
    };

    const updateRowField = <K extends EditableWeeklyField>(
        assistantId: string,
        key: K,
        value: WeeklyDraftRow[K],
    ) => {
        updateRowDraft(assistantId, (draft) => ({
            ...draft,
            [key]: value,
        }));
    };

    const handleSaveRow = async (assistantId: string) => {
        const draft = rowDrafts[assistantId];
        if (!draft) return;

        setSavingRows((current) => ({
            ...current,
            [assistantId]: true,
        }));
        setRowErrors((current) => ({
            ...current,
            [assistantId]: null,
        }));

        try {
            const response = await apiFetch(`/api/assistant-weekly/admin/${assistantId}?week_start=${adminWeek?.week_start ?? weekStart}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    day_overrides: draft.days.map((day) => ({
                        work_date: day.work_date,
                        manual_status: day.manual_status ?? null,
                        is_manual_override: day.status_source === 'manual',
                    })),
                    selected_result: draft.selected_result ?? null,
                    payout_type: draft.payout_type ?? null,
                    payout_server: draft.payout_server ?? null,
                    payout_static: draft.payout_static ?? null,
                }),
            });
            const data = await response.json().catch(() => ({} as unknown));
            if (!response.ok) {
                throw new Error(getApiErrorMessage(data, 'Не удалось сохранить недельную статистику'));
            }

            const saved = recomputeCounts(cloneDraft(unwrapApiData<WeeklyAssistantDetail>(data)));

            setAdminWeek((current) => current ? {
                ...current,
                items: current.items.map((item) => (item.assistant_id === assistantId ? saved : item)),
            } : current);
            setRowDrafts((current) => ({
                ...current,
                [assistantId]: saved,
            }));
            showToast('Недельная статистика сохранена');
        } catch (error: unknown) {
            const message = error instanceof Error ? error.message : 'Не удалось сохранить недельную статистику';
            setRowErrors((current) => ({
                ...current,
                [assistantId]: message,
            }));
            showToast(message, 'error');
        } finally {
            setSavingRows((current) => ({
                ...current,
                [assistantId]: false,
            }));
        }
    };

    const handleCopyCommand = async (assistantId: string) => {
        const draft = rowDrafts[assistantId];
        if (!draft) return;
        const commandState = getCommandState(baseRowsById[assistantId], draft);
        if (!commandState.command) return;

        try {
            await navigator.clipboard.writeText(commandState.command);
            showToast('Команда скопирована');
        } catch {
            showToast('Не удалось скопировать команду', 'error');
        }
    };

    const handleUpdatePayoutIssueStatus = async (
        assistantId: string,
        nextStatus: WeeklyPayoutIssueStatus,
    ) => {
        setIssuingRows((current) => ({
            ...current,
            [assistantId]: true,
        }));
        setRowErrors((current) => ({
            ...current,
            [assistantId]: null,
        }));

        try {
            const response = await apiFetch(
                `/api/assistant-weekly/admin/${assistantId}/payout-issue?week_start=${adminWeek?.week_start ?? weekStart}`,
                {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status: nextStatus }),
                },
            );
            const data = await response.json().catch(() => ({} as unknown));
            if (!response.ok) {
                throw new Error(getApiErrorMessage(data, 'Не удалось обновить статус выдачи'));
            }

            const saved = recomputeCounts(cloneDraft(unwrapApiData<WeeklyAssistantDetail>(data)));
            setAdminWeek((current) => current ? {
                ...current,
                items: current.items.map((item) => (item.assistant_id === assistantId ? saved : item)),
            } : current);
            setRowDrafts((current) => ({
                ...current,
                [assistantId]: saved,
            }));
            showToast(nextStatus === 'issued' ? 'Выдача отмечена' : 'Отметка выдачи снята');
        } catch (error: unknown) {
            const message = error instanceof Error ? error.message : 'Не удалось обновить статус выдачи';
            setRowErrors((current) => ({
                ...current,
                [assistantId]: message,
            }));
            showToast(message, 'error');
        } finally {
            setIssuingRows((current) => ({
                ...current,
                [assistantId]: false,
            }));
        }
    };

    return (
        <div className="space-y-6 animate-[fadeIn_0.35s_ease-in-out]">
            <div className="flex flex-col gap-4 border-b border-white/10 pb-6">
                <div className="flex items-start gap-4">
                    <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-fuchsia-500/30 bg-fuchsia-500/15 text-fuchsia-100">
                        <CalendarClock className="h-6 w-6" />
                    </div>
                    <div className="space-y-1">
                        <h2 className="text-2xl font-bold text-white">Недельная статистика ассистентов</h2>
                    </div>
                </div>
            </div>

            <div className="flex flex-col gap-4 rounded-2xl border border-white/5 bg-[#1e1e1e] p-4">
                <div className="flex flex-wrap items-center gap-3">
                    <label className="flex items-center gap-2 text-sm text-white/55">
                        <span className="text-white/40">Неделя</span>
                        <input
                            type="date"
                            value={weekStart}
                            onChange={(event) => setWeekStart(normalizeWeekStart(event.target.value))}
                            className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-white outline-none focus:border-fuchsia-500/40"
                        />
                    </label>
                    <div className="text-sm text-white/45">
                        {adminWeek ? formatWeekRange(adminWeek.week_start, adminWeek.week_end) : '—'}
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
                        <input
                            value={search}
                            onChange={(event) => setSearch(event.target.value)}
                            placeholder="Поиск по нику"
                            className="w-72 max-w-[72vw] rounded-xl border border-white/10 bg-black/20 py-2.5 pl-10 pr-3 text-sm text-white outline-none placeholder:text-white/30 focus:border-fuchsia-500/40"
                        />
                    </div>
                    <button
                        type="button"
                        onClick={() => void loadAdmin(weekStart)}
                        className="inline-flex items-center gap-2 rounded-xl border border-fuchsia-500/20 bg-fuchsia-500/15 px-4 py-2.5 text-sm font-medium text-fuchsia-100 transition hover:bg-fuchsia-500/20"
                    >
                        <RefreshCw className="h-4 w-4" />
                        Обновить
                    </button>
                </div>
            </div>

            <div className="flex flex-col gap-3 rounded-2xl border border-white/5 bg-[#1e1e1e] p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <span className="text-sm text-white/40">
                        Показано <span className="font-semibold text-white">{filteredRows.length}</span> из <span className="font-semibold text-white">{summary.total}</span>
                    </span>
                    <span className="text-xs font-semibold uppercase tracking-[0.16em] text-white/35">Фильтр недели</span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    {summaryCards.map((card) => {
                        const active = filterMode === card.mode;
                        return (
                            <button
                                key={card.mode}
                                type="button"
                                onClick={() => setFilterMode(card.mode)}
                                className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm transition hover:border-white/20 ${card.tone} ${active ? 'ring-1 ring-white/20 shadow-[0_0_0_1px_rgba(255,255,255,0.08)]' : ''}`}
                            >
                                <span>{card.label}</span>
                                <span className="rounded-full border border-current/20 bg-black/20 px-2 py-0.5 text-xs font-semibold">
                                    {card.count}
                                </span>
                            </button>
                        );
                    })}
                </div>
            </div>

            {loading ? (
                <div className="rounded-2xl border border-white/5 bg-white/5 p-8 text-center text-white/40">Загрузка...</div>
            ) : (
                <div className="rounded-2xl border border-white/5 bg-[#1e1e1e] overflow-hidden">
                    <table className="w-full table-fixed border-collapse text-sm">
                        <colgroup>
                            <col className="w-[12%]" />
                            <col className="w-[8%]" />
                            <col className="w-[8%]" />
                            <col className="w-[8%]" />
                            <col className="w-[8%]" />
                            <col className="w-[8%]" />
                            <col className="w-[8%]" />
                            <col className="w-[8%]" />
                            <col className="w-[8%]" />
                            <col className="w-[10%]" />
                            <col className="w-[14%]" />
                        </colgroup>
                        <thead className="sticky top-0 z-30 bg-[#242424]">
                            <tr className="border-b border-white/10">
                                <th className="bg-[#242424] px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.16em] text-white/45">
                                    Ассистент
                                </th>
                                {headerDays.map((day) => (
                                    <th key={day.work_date} className="border-l border-white/5 px-3 py-3 text-left text-xs font-semibold uppercase tracking-[0.16em] text-white/45">
                                        <div className="space-y-1">
                                            <div>{day.label}</div>
                                            <div className="text-[11px] font-medium tracking-normal text-white/25">{day.short_date}</div>
                                        </div>
                                    </th>
                                ))}
                                <th className="border-l border-white/5 px-3 py-3 text-left text-xs font-semibold uppercase tracking-[0.16em] text-white/45">Итого</th>
                                <th className="border-l border-white/5 px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.16em] text-white/45">Решение</th>
                                <th className="border-l border-white/5 px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.16em] text-white/45">Выплата</th>
                            </tr>
                        </thead>
                        <tbody>
                            {filteredRows.length === 0 ? (
                                <tr>
                                    <td colSpan={11} className="px-6 py-12 text-center text-white/40">
                                        Ничего не найдено
                                    </td>
                                </tr>
                            ) : (
                                filteredRows.map((row) => {
                                    const baseRow = baseRowsById[row.assistant_id];
                                    const dirty = isRowDirty(baseRow, row);
                                    const commandState = getCommandState(baseRow, row);
                                    const isSaving = Boolean(savingRows[row.assistant_id]);
                                    const isIssuing = Boolean(issuingRows[row.assistant_id]);
                                    const payoutDisplayState = getPayoutDisplayState(row, baseRow);
                                    const payoutStatusMeta = getPayoutStatusMeta(payoutDisplayState);
                                    const shouldWarnPayoutReset = (
                                        row.payout_issue_status === 'issued'
                                        && areCommandInputsDirty(baseRow, row)
                                    );
                                    const disableIssueMark = (
                                        payoutDisplayState !== 'ready'
                                        || dirty
                                        || isSaving
                                        || isIssuing
                                    );

                                    return (
                                        <tr
                                            key={row.assistant_id}
                                            className={`border-b border-white/5 align-top transition-colors hover:bg-white/[0.03] ${dirty ? 'bg-fuchsia-500/[0.025]' : ''}`}
                                        >
                                            <td className="px-4 py-4">
                                                <div className="flex items-start gap-3">
                                                    <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-fuchsia-500/20 bg-fuchsia-500/10 text-fuchsia-100">
                                                        <UserRound className="h-4 w-4" />
                                                    </div>
                                                    <div className="min-w-0 space-y-1">
                                                        <div className="flex flex-wrap items-center gap-2">
                                                            <div className="font-semibold text-white">{row.nickname}</div>
                                                            <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] ${dirty ? 'border-fuchsia-500/30 bg-fuchsia-500/15 text-fuchsia-100' : 'border-white/10 bg-white/5 text-white/50'}`}>
                                                                {dirty ? 'Черновик' : 'Сохранено'}
                                                            </span>
                                                        </div>
                                                        <div className="flex flex-wrap items-center gap-2 text-xs text-white/40">
                                                            <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] ${getRoleTone(row.role)}`}>
                                                                {getRoleLabel(row.role)}
                                                            </span>
                                                        </div>
                                                    </div>
                                                </div>
                                            </td>

                                            {row.days.map((day, index) => (
                                                <td key={`${row.assistant_id}-${day.work_date}`} className="border-l border-white/5 px-3 py-3">
                                                    <div className="min-h-[126px] rounded-2xl border border-white/8 bg-white/[0.025] p-2.5">
                                                        <div className="flex items-start justify-between gap-2">
                                                            <div className="text-[15px] font-semibold tabular-nums text-white">
                                                                {formatHours(day.spec_hours_on_day)}
                                                            </div>
                                                            {day.resolved_status ? (
                                                                <span className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] ${getStatusTone(day.resolved_status)}`}>
                                                                    {getStatusLabel(day.resolved_status)}
                                                                </span>
                                                            ) : null}
                                                        </div>

                                                        <div className="mt-2 grid grid-cols-2 gap-2 border-t border-white/6 pt-2 text-[10px]">
                                                            <div className="rounded-lg bg-black/15 px-2 py-1.5">
                                                                <div className="text-white/30">M-чат</div>
                                                                <div className="mt-1 font-semibold tabular-nums text-white">{day.mchat_count}</div>
                                                            </div>
                                                            <div className="rounded-lg bg-black/15 px-2 py-1.5">
                                                                <div className="text-white/30">Жалобы</div>
                                                                <div className="mt-1 font-semibold tabular-nums text-white">{day.complaints_count}</div>
                                                            </div>
                                                        </div>

                                                        <select
                                                            aria-label={`Статус дня ${row.nickname} ${day.weekday_label ?? WEEKDAY_LABELS[index]}`}
                                                            value={getDayControlValue(day)}
                                                            onChange={(event) => updateRowDayStatus(row.assistant_id, day.work_date, event.target.value as WeeklyDayControlValue)}
                                                            className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-2.5 py-2 text-[11px] text-white outline-none focus:border-fuchsia-500/40"
                                                        >
                                                            {getDayControlOptions(day).map((option) => (
                                                                <option key={option.value} value={option.value}>
                                                                    {option.label}
                                                                </option>
                                                            ))}
                                                        </select>
                                                    </div>
                                                </td>
                                            ))}

                                            <td className="border-l border-white/5 px-3 py-3">
                                                <div className="rounded-2xl border border-white/8 bg-white/[0.025] p-3">
                                                    <div className="flex items-end justify-between gap-2">
                                                        <div>
                                                            <div className="text-[10px] uppercase tracking-[0.14em] text-white/35">Итого</div>
                                                            <div className="mt-1 text-lg font-semibold tabular-nums text-white">{formatHours(row.total_spec_hours)}</div>
                                                        </div>
                                                        <div className="text-[10px] uppercase tracking-[0.14em] text-white/28">Слежка</div>
                                                    </div>
                                                    <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                                                        <div className="rounded-lg bg-black/15 px-2 py-2">
                                                            <div className="text-white/30">M-чат</div>
                                                            <div className="mt-1 font-semibold tabular-nums text-white">{row.total_mchat}</div>
                                                        </div>
                                                        <div className="rounded-lg bg-black/15 px-2 py-2">
                                                            <div className="text-white/30">Жалобы</div>
                                                            <div className="mt-1 font-semibold tabular-nums text-white">{row.total_complaints}</div>
                                                        </div>
                                                    </div>
                                                    <div className="mt-2 grid grid-cols-3 gap-1.5 text-[11px]">
                                                        <span className="rounded-lg border border-rose-500/20 bg-rose-500/10 px-2 py-1.5 text-center text-rose-100">П {row.count_P}</span>
                                                        <span className="rounded-lg border border-sky-500/20 bg-sky-500/10 px-2 py-1.5 text-center text-sky-100">У {row.count_U}</span>
                                                        <span className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-2 py-1.5 text-center text-amber-100">О {row.count_O}</span>
                                                    </div>
                                                </div>
                                            </td>

                                            <td className="border-l border-white/5 px-4 py-3">
                                                <div className="space-y-2.5 rounded-2xl border border-white/8 bg-white/[0.025] p-3">
                                                    <div className="text-[10px] uppercase tracking-[0.14em] text-white/35">Предложено</div>
                                                    <span className={`inline-flex items-center rounded-full border px-3 py-1.5 text-xs font-medium ${getResultTone(row.suggested_result)}`}>
                                                        {row.suggested_result ?? '—'}
                                                    </span>
                                                    <select
                                                        aria-label={`Selected result ${row.nickname}`}
                                                        value={row.selected_result ?? ''}
                                                        onChange={(event) => updateRowField(row.assistant_id, 'selected_result', (event.target.value || null) as WeeklyDraftRow['selected_result'])}
                                                        className="w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs text-white outline-none focus:border-fuchsia-500/40"
                                                    >
                                                        <option value="">—</option>
                                                        {(adminWeek?.result_options?.length ? adminWeek.result_options : FALLBACK_RESULT_OPTIONS).map((option) => (
                                                            <option key={option} value={option}>{option}</option>
                                                        ))}
                                                    </select>
                                                </div>
                                            </td>

                                            <td className="border-l border-white/5 px-4 py-3">
                                                <div className="space-y-2.5 rounded-2xl border border-white/8 bg-white/[0.025] p-3">
                                                    <div className="grid grid-cols-2 gap-2">
                                                        <select
                                                            aria-label={`Payout type ${row.nickname}`}
                                                            value={row.payout_type ?? ''}
                                                            onChange={(event) => updateRowField(row.assistant_id, 'payout_type', (event.target.value || null) as WeeklyDraftRow['payout_type'])}
                                                            className="w-full rounded-xl border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white outline-none focus:border-cyan-500/40"
                                                        >
                                                            <option value="">Тип</option>
                                                            {(adminWeek?.payout_types?.length ? adminWeek.payout_types : FALLBACK_PAYOUT_TYPES).map((option) => (
                                                                <option key={option.value} value={option.value}>{option.label}</option>
                                                            ))}
                                                        </select>
                                                        <select
                                                            aria-label={`Payout server ${row.nickname}`}
                                                            value={row.payout_server ?? ''}
                                                            onChange={(event) => updateRowField(row.assistant_id, 'payout_server', (event.target.value || null) as WeeklyDraftRow['payout_server'])}
                                                            className="w-full rounded-xl border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white outline-none focus:border-cyan-500/40"
                                                        >
                                                            <option value="">Сервер</option>
                                                            {payoutServers.map((server) => (
                                                                <option key={server} value={server}>{server}</option>
                                                            ))}
                                                        </select>
                                                    </div>
                                                    <input
                                                        aria-label={`Payout static ${row.nickname}`}
                                                        value={row.payout_static ?? ''}
                                                        onChange={(event) => updateRowField(row.assistant_id, 'payout_static', event.target.value)}
                                                        placeholder="static"
                                                        className="w-full rounded-xl border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white outline-none placeholder:text-white/25 focus:border-cyan-500/40"
                                                    />
                                                    <div
                                                        className="rounded-xl border border-white/8 bg-black/15 px-3 py-2.5"
                                                        title={commandState.command ?? commandState.reason ?? ''}
                                                    >
                                                        <div className="text-[10px] uppercase tracking-[0.14em] text-white/30">Команда</div>
                                                        <div className="mt-1 font-mono text-[10px] leading-5 text-white/85 break-all whitespace-normal">
                                                            {commandState.command ?? commandState.reason}
                                                        </div>
                                                    </div>
                                                    <div className="space-y-2">
                                                        <div className="flex items-center justify-between gap-2">
                                                            <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] ${payoutStatusMeta.tone}`}>
                                                                {payoutStatusMeta.label}
                                                            </span>
                                                            <button
                                                                type="button"
                                                                aria-label={`Скопировать команду ${row.nickname}`}
                                                                onClick={() => void handleCopyCommand(row.assistant_id)}
                                                                disabled={!commandState.command}
                                                                className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-medium text-white transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40"
                                                            >
                                                                <ClipboardCopy className="h-4 w-4" />
                                                                Скопировать
                                                            </button>
                                                        </div>
                                                        {row.payout_issue_status === 'issued' && row.payout_issued_at ? (
                                                            <div className="text-[11px] text-white/45">
                                                                Выдано {formatMskToLocal(row.payout_issued_at, {
                                                                    day: '2-digit',
                                                                    month: '2-digit',
                                                                    hour: '2-digit',
                                                                    minute: '2-digit',
                                                                })}
                                                            </div>
                                                        ) : null}
                                                        {shouldWarnPayoutReset ? (
                                                            <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                                                                После сохранения отметка выдачи будет снята
                                                            </div>
                                                        ) : null}
                                                        {dirty && payoutDisplayState !== 'issued' ? (
                                                            <div className="text-[11px] text-white/45">
                                                                Сначала сохраните строку
                                                            </div>
                                                        ) : null}
                                                        {row.payout_issue_status === 'issued' ? (
                                                            <button
                                                                type="button"
                                                                aria-label={`Снять выдачу ${row.nickname}`}
                                                                onClick={() => void handleUpdatePayoutIssueStatus(row.assistant_id, 'pending')}
                                                                disabled={isIssuing}
                                                                className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-white transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
                                                            >
                                                                {isIssuing ? (
                                                                    <RefreshCw className="h-4 w-4 animate-spin" />
                                                                ) : (
                                                                    <CheckCircle2 className="h-4 w-4" />
                                                                )}
                                                                Снять выдачу
                                                            </button>
                                                        ) : (
                                                            <button
                                                                type="button"
                                                                aria-label={`Отметить выдано ${row.nickname}`}
                                                                onClick={() => void handleUpdatePayoutIssueStatus(row.assistant_id, 'issued')}
                                                                disabled={disableIssueMark}
                                                                className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/15 px-4 py-2 text-sm font-medium text-emerald-100 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                                                            >
                                                                {isIssuing ? (
                                                                    <RefreshCw className="h-4 w-4 animate-spin" />
                                                                ) : (
                                                                    <CheckCircle2 className="h-4 w-4" />
                                                                )}
                                                                Отметить выдано
                                                            </button>
                                                        )}
                                                        <button
                                                            type="button"
                                                            aria-label={`Сохранить ${row.nickname}`}
                                                            onClick={() => void handleSaveRow(row.assistant_id)}
                                                            disabled={isSaving || isIssuing}
                                                            className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-fuchsia-500/20 bg-fuchsia-500/15 px-4 py-2 text-sm font-medium text-fuchsia-100 transition hover:bg-fuchsia-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                                                        >
                                                            {isSaving ? (
                                                                <RefreshCw className="h-4 w-4 animate-spin" />
                                                            ) : (
                                                                <CheckCircle2 className="h-4 w-4" />
                                                            )}
                                                            Сохранить
                                                        </button>
                                                    </div>
                                                    {rowErrors[row.assistant_id] && (
                                                        <div className="rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-100">
                                                            {rowErrors[row.assistant_id]}
                                                        </div>
                                                    )}
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })
                            )}
                        </tbody>
                    </table>
                </div>
            )}

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

export default AssistantWeeklyStatsManagement;
