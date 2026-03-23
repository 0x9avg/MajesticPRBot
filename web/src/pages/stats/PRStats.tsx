import React from 'react';
import { Link, useNavigate, useOutletContext, useSearchParams } from 'react-router-dom';
import {
    CalendarClock,
    ChevronDown,
    ChevronUp,
    RefreshCw,
    Search,
} from 'lucide-react';

import { apiFetch } from '../../api/client';
import type { OutletUserContext } from '../../types/auth';
import type { Assistant, WeeklyCurrentResponse } from '../../types/domain';
import { unwrapApiData } from '../../types/api';
import { hasPerm } from '../../rbac/guards';
import { formatAssistantWarnings } from '../../utils/warnings';

type SortKey =
    | 'nickname'
    | 'role'
    | 'experience_days'
    | 'status'
    | 'total_spec_hours'
    | 'avg_spec_hours_per_day_30d'
    | 'gross_points'
    | 'net_points'
    | 'warnings'
    | 'active_point_penalty'
    | 'active_percent_penalty';

type AssistantsTab = 'stats' | 'active';

const getDayStatusTone = (value: string | null | undefined) => {
    switch (value) {
        case 'P':
            return 'bg-rose-500/15 text-rose-200 border-rose-500/30';
        case 'U':
            return 'bg-sky-500/15 text-sky-200 border-sky-500/30';
        case 'O':
            return 'bg-amber-500/15 text-amber-200 border-amber-500/30';
        default:
            return 'bg-white/5 text-white/55 border-white/10';
    }
};

const getDayStatusLabel = (value: string | null | undefined) => {
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
            return 'bg-red-500/20 text-red-400 border-red-500/30';
        case 'manager':
            return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
        case 'senior_employee':
            return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
        case 'employee':
            return 'bg-gray-500/20 text-gray-300 border-gray-500/30';
        case 'junior_employee':
            return 'bg-gray-500/10 text-gray-500 border-gray-500/20';
        default:
            return 'bg-white/10 text-white/60 border-white/10';
    }
};

const formatWeeklyHours = (value: number | undefined) => {
    const normalized = Number(value || 0);
    return `${normalized.toFixed(1).replace(/\.0$/, '')}ч`;
};

const formatWeekRange = (weekStart?: string | null, weekEnd?: string | null) => {
    if (!weekStart || !weekEnd) return '—';
    const [startYear, startMonth, startDay] = weekStart.split('-');
    const [endYear, endMonth, endDay] = weekEnd.split('-');
    const endLabel = endYear === startYear ? `${endDay}.${endMonth}` : `${endDay}.${endMonth}.${endYear}`;
    return `${startDay}.${startMonth} - ${endLabel}`;
};

export function PRStats() {
    const navigate = useNavigate();
    const { user } = useOutletContext<OutletUserContext>();
    const [searchParams] = useSearchParams();
    const canViewAssistants = hasPerm(user, 'assistants.view');
    const [assistants, setAssistants] = React.useState<Assistant[]>([]);
    const [loading, setLoading] = React.useState(true);
    const [activeLoading, setActiveLoading] = React.useState(true);
    const [error, setError] = React.useState<string | null>(null);
    const [weeklySearch, setWeeklySearch] = React.useState('');
    const [currentWeek, setCurrentWeek] = React.useState<WeeklyCurrentResponse | null>(null);
    const [sortConfig, setSortConfig] = React.useState<{ key: SortKey, direction: 'asc' | 'desc' }>({ key: 'role', direction: 'desc' });

    const activeTab: AssistantsTab = searchParams.get('tab') === 'active' ? 'active' : 'stats';

    const fetchAssistants = React.useCallback(async (silent = false) => {
        if (!canViewAssistants) {
            setAssistants([]);
            setError('Недостаточно прав для просмотра таблицы ассистентов.');
            if (!silent) setLoading(false);
            return;
        }
        if (!silent) setLoading(true);
        try {
            setError(null);
            const response = await apiFetch('/api/assistants');
            if (response.ok) {
                const json = await response.json() as unknown;
                const data = unwrapApiData<Assistant[] | { assistants: Assistant[] }>(json);
                const normalized = Array.isArray(data) ? data : data.assistants;
                setAssistants(Array.isArray(normalized) ? normalized : []);
            } else if (response.status === 403) {
                setAssistants([]);
                setError('Недостаточно прав для просмотра таблицы ассистентов.');
            } else {
                setError('Не удалось загрузить таблицу ассистентов.');
            }
        } catch (error) {
            console.error('Failed to fetch assistants:', error);
            setError('Не удалось загрузить таблицу ассистентов.');
        } finally {
            if (!silent) setLoading(false);
        }
    }, [canViewAssistants]);

    const fetchActiveWeek = React.useCallback(async (silent = false) => {
        if (!canViewAssistants) {
            setCurrentWeek(null);
            if (!silent) setActiveLoading(false);
            return;
        }
        if (!silent) setActiveLoading(true);
        try {
            const response = await apiFetch('/api/assistant-weekly/current');
            if (response.ok) {
                const json = await response.json() as unknown;
                const data = unwrapApiData<WeeklyCurrentResponse>(json);
                setCurrentWeek(data);
            }
        } catch (error) {
            console.error('Failed to fetch weekly activity:', error);
        } finally {
            if (!silent) setActiveLoading(false);
        }
    }, [canViewAssistants]);

    React.useEffect(() => {
        void fetchAssistants();
        void fetchActiveWeek();
        if (!canViewAssistants) {
            return undefined;
        }
        const interval = setInterval(() => {
            void fetchAssistants(true);
            void fetchActiveWeek(true);
        }, 10000);
        return () => clearInterval(interval);
    }, [canViewAssistants, fetchAssistants, fetchActiveWeek]);

    const handleSort = (key: SortKey) => {
        let direction: 'asc' | 'desc' = 'asc';
        if (sortConfig.key === key && sortConfig.direction === 'asc') {
            direction = 'desc';
        }
        setSortConfig({ key, direction });
    };

    const getSortValue = (assistant: Assistant, key: SortKey): string | number => {
        switch (key) {
            case 'nickname':
                return assistant.nickname || '';
            case 'role':
                return assistant.role || '';
            case 'experience_days':
                return assistant.experience_days || 0;
            case 'status':
                return assistant.status === 'assigned' ? 1 : 0;
            case 'total_spec_hours':
                return assistant.total_spec_hours || 0;
            case 'avg_spec_hours_per_day_30d':
                return assistant.avg_spec_hours_per_day_30d || 0;
            case 'gross_points':
                return assistant.gross_points ?? 0;
            case 'net_points':
                return assistant.net_points ?? assistant.gross_points ?? 0;
            case 'active_point_penalty':
                return assistant.active_point_penalty || 0;
            case 'active_percent_penalty':
                return assistant.active_percent_penalty || 0;
            case 'warnings':
                return (assistant.active_strict_warnings || 0) * 10 + (assistant.active_oral_warnings || 0);
            default:
                return 0;
        }
    };

    const getSortedAssistants = () => {
        const sorted = [...assistants];
        sorted.sort((a, b) => {
            if (sortConfig.key === 'role') {
                const roleWeights: Record<string, number> = {
                    developer: 4,
                    manager: 3,
                    senior_employee: 2,
                    employee: 1,
                    junior_employee: 0,
                };
                const weightA = roleWeights[a.role as keyof typeof roleWeights] || 0;
                const weightB = roleWeights[b.role as keyof typeof roleWeights] || 0;
                return sortConfig.direction === 'asc' ? weightA - weightB : weightB - weightA;
            }

            if (sortConfig.key === 'status') {
                const statusA = getSortValue(a, sortConfig.key) as number;
                const statusB = getSortValue(b, sortConfig.key) as number;
                if (statusA !== statusB) {
                    return sortConfig.direction === 'asc' ? statusA - statusB : statusB - statusA;
                }
                const nameA = a.assigned_to_name || '';
                const nameB = b.assigned_to_name || '';
                return sortConfig.direction === 'asc'
                    ? nameA.localeCompare(nameB)
                    : nameB.localeCompare(nameA);
            }

            const aValue = getSortValue(a, sortConfig.key);
            const bValue = getSortValue(b, sortConfig.key);
            if (aValue < bValue) {
                return sortConfig.direction === 'asc' ? -1 : 1;
            }
            if (aValue > bValue) {
                return sortConfig.direction === 'asc' ? 1 : -1;
            }
            return 0;
        });
        return sorted;
    };

    const weeklyItems = React.useMemo(() => {
        const query = weeklySearch.trim().toLowerCase();
        const items = currentWeek?.items ?? [];
        if (!query) return items;
        return items.filter((assistant) =>
            assistant.nickname.toLowerCase().includes(query)
            || assistant.assistant_id.includes(query),
        );
    }, [currentWeek?.items, weeklySearch]);

    const penaltyPointsSortedPositive = React.useMemo(
        () =>
            assistants
                .map((assistant) => Number(assistant.active_point_penalty || 0))
                .filter((value) => value > 0)
                .sort((a, b) => a - b),
        [assistants],
    );

    const penaltyPercentSortedPositive = React.useMemo(
        () =>
            assistants
                .map((assistant) => Number(assistant.active_percent_penalty || 0))
                .filter((value) => value > 0)
                .sort((a, b) => a - b),
        [assistants],
    );

    const getRelativePenaltyClass = (
        value: number,
        sortedPositiveValues: number[],
    ): string => {
        if (value <= 0) {
            return 'bg-white/5 text-white/60 border-white/10';
        }

        if (sortedPositiveValues.length < 3) {
            return 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30';
        }

        const firstIndex = sortedPositiveValues.findIndex((current) => current === value);
        let lastIndex = -1;
        for (let i = sortedPositiveValues.length - 1; i >= 0; i -= 1) {
            if (sortedPositiveValues[i] === value) {
                lastIndex = i;
                break;
            }
        }

        if (firstIndex === -1 || lastIndex === -1) {
            return 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30';
        }

        const midRank = (firstIndex + lastIndex) / 2;
        const percentile = ((midRank + 1) / sortedPositiveValues.length) * 100;

        if (percentile <= 50) {
            return 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30';
        }
        if (percentile <= 85) {
            return 'bg-orange-500/15 text-orange-300 border-orange-500/30';
        }
        return 'bg-red-500/15 text-red-300 border-red-500/30';
    };

    const getWarningsBadgeClass = (assistant: Assistant): string => {
        const strict = assistant.active_strict_warnings || 0;
        const oral = assistant.active_oral_warnings || 0;

        if (strict >= 1 && oral >= 1) return 'bg-red-500/15 text-red-300 border-red-500/30';
        if (strict >= 1) return 'bg-orange-500/15 text-orange-300 border-orange-500/30';
        if (oral >= 1) return 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30';
        return 'bg-white/5 text-white/50 border-white/10';
    };

    const formatHours = (value: number | undefined) =>
        Number(value || 0).toFixed(2);

    const getRoleBadge = (role: string) => {
        const styles: Record<string, string> = {
            developer: 'bg-red-500/20 text-red-400 border-red-500/30',
            manager: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
            senior_employee: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
            employee: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
            junior_employee: 'bg-gray-500/10 text-gray-500 border-gray-500/20',
        };

        const labels: Record<string, string> = {
            developer: 'Разработчик',
            manager: 'Глав. ассистент',
            senior_employee: 'Ст. ассистент',
            employee: 'Ассистент',
            junior_employee: 'Мл. ассистент',
        };

        const style = styles[role] || 'bg-white/10 text-white/60 border-white/10';
        const label = labels[role] || role;

        return (
            <span
                className={`inline-flex max-w-full items-center px-2.5 py-1 rounded-full text-xs font-medium border whitespace-nowrap truncate ${style}`}
                title={label}
            >
                {label}
            </span>
        );
    };

    const getStatusBadge = (assistant: Assistant) => {
        if (assistant.status === 'free') {
            return (
                <span className="inline-flex px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap bg-green-500/20 text-green-400 border border-green-500/30">
                    Свободен
                </span>
            );
        }

        const typeLabel = assistant.assigned_to_type === 'streamer' ? '🎥 Стример' : '🎉 Ивент';
        return (
            <div className="flex flex-col gap-1">
                <span className="inline-flex w-fit px-3 py-1 rounded-full text-xs font-medium whitespace-nowrap bg-purple-500/20 text-purple-400 border border-purple-500/30">
                    В закрепе
                </span>
                <span
                    className="text-xs text-white/50 truncate"
                    title={`${typeLabel}: ${assistant.assigned_to_name ?? ''}`}
                >
                    {typeLabel}: {assistant.assigned_to_name}
                </span>
            </div>
        );
    };

    const SortIcon = ({ columnKey }: { columnKey: string }) => {
        if (sortConfig.key !== columnKey) return <div className="w-4 h-4" />;
        return sortConfig.direction === 'asc'
            ? <ChevronUp className="w-4 h-4 text-[#3b82f6]" />
            : <ChevronDown className="w-4 h-4 text-[#3b82f6]" />;
    };

    const renderHeader = (label: string, sortKey: SortKey) => (
        <th
            className="text-left p-3 text-xs font-semibold text-white/60 select-none cursor-pointer hover:text-white transition-colors group whitespace-nowrap"
            onClick={() => handleSort(sortKey)}
        >
            <div className="flex items-center gap-2">
                {label}
                <SortIcon columnKey={sortKey} />
            </div>
        </th>
    );

    const statsContent = loading ? (
        <div className="flex items-center justify-center h-64">
            <div className="text-white/60">Загрузка...</div>
        </div>
    ) : (
        <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden">
            <table className="w-full table-fixed text-sm">
                <colgroup>
                    <col className="w-[13%]" />
                    <col className="w-[10%]" />
                    <col className="w-[7%]" />
                    <col className="w-[15%]" />
                    <col className="w-[8%]" />
                    <col className="w-[9%]" />
                    <col className="w-[7%]" />
                    <col className="w-[7%]" />
                    <col className="w-[8%]" />
                    <col className="w-[8%]" />
                    <col className="w-[8%]" />
                </colgroup>
                <thead className="sticky top-0 z-10 bg-[#242424]">
                    <tr className="border-b border-white/5">
                        {renderHeader('Ник', 'nickname')}
                        {renderHeader('Должность', 'role')}
                        {renderHeader('Стаж', 'experience_days')}
                        {renderHeader('Статус', 'status')}
                        {renderHeader('Общее время', 'total_spec_hours')}
                        {renderHeader('Ср. ч/день', 'avg_spec_hours_per_day_30d')}
                        {renderHeader('Общие баллы', 'gross_points')}
                        {renderHeader('После санк.', 'net_points')}
                        {renderHeader('Штраф. баллы', 'active_point_penalty')}
                        {renderHeader('Штраф, %', 'active_percent_penalty')}
                        {renderHeader('Выговоры', 'warnings')}
                    </tr>
                </thead>
                <tbody>
                    {assistants.length === 0 ? (
                        <tr>
                            <td colSpan={11} className="text-center py-12 text-white/40 select-none">
                                Нет данных
                            </td>
                        </tr>
                    ) : (
                        getSortedAssistants().map((assistant) => (
                            <tr
                                key={assistant.pr_id}
                                className="border-b border-white/5 hover:bg-white/5 transition-colors"
                            >
                                <td className="p-3">
                                    <div
                                        className="flex items-center gap-2 cursor-pointer group"
                                        onClick={() => navigate(`/assistants/${assistant.pr_id}`)}
                                        title="Перейти в профиль"
                                    >
                                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[#3b82f6] to-[#e81c5a] flex items-center justify-center text-white font-bold text-sm">
                                            {(assistant.nickname?.charAt(0) || '?').toUpperCase()}
                                        </div>
                                        <span className="font-medium text-white group-hover:text-[#3b82f6] transition-colors truncate" title={assistant.nickname}>
                                            {assistant.nickname}
                                        </span>
                                    </div>
                                </td>
                                <td className="p-3">{getRoleBadge(assistant.role)}</td>
                                <td className="p-3 text-white/80 whitespace-nowrap">
                                    {assistant.experience_days} {assistant.experience_days === 1 ? 'день' : 'дней'}
                                </td>
                                <td className="p-3">{getStatusBadge(assistant)}</td>
                                <td className="p-3 text-white/80 font-mono whitespace-nowrap">
                                    {formatHours(assistant.total_spec_hours)}ч
                                </td>
                                <td className="p-3 text-white/80 font-mono whitespace-nowrap">
                                    {formatHours(
                                        assistant.avg_spec_hours_per_day_30d ??
                                        ((assistant.total_spec_hours || 0) / 30),
                                    )}ч
                                </td>
                                <td className="p-3 whitespace-nowrap">
                                    <span className="inline-flex px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap bg-blue-500/15 text-blue-300 border-blue-500/30">
                                        {(assistant.gross_points ?? 0).toFixed(2)}
                                    </span>
                                </td>
                                <td className="p-3 whitespace-nowrap">
                                    <span className="inline-flex px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap bg-green-500/15 text-green-300 border-green-500/30">
                                        {(assistant.net_points ?? assistant.gross_points ?? 0).toFixed(2)}
                                    </span>
                                </td>
                                <td className="p-3 whitespace-nowrap">
                                    <span
                                        className={`inline-flex px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap ${getRelativePenaltyClass(
                                            Number(assistant.active_point_penalty || 0),
                                            penaltyPointsSortedPositive,
                                        )}`}
                                    >
                                        {Number(assistant.active_point_penalty || 0)}
                                    </span>
                                </td>
                                <td className="p-3 whitespace-nowrap">
                                    <span
                                        className={`inline-flex px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap ${getRelativePenaltyClass(
                                            Number(assistant.active_percent_penalty || 0),
                                            penaltyPercentSortedPositive,
                                        )}`}
                                    >
                                        {Number(assistant.active_percent_penalty || 0)}%
                                    </span>
                                </td>
                                <td className="p-3 whitespace-nowrap">
                                    <span className={`inline-flex px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap ${getWarningsBadgeClass(assistant)}`}>
                                        {formatAssistantWarnings(
                                            assistant.active_strict_warnings,
                                            assistant.active_oral_warnings,
                                        )}
                                    </span>
                                </td>
                            </tr>
                        ))
                    )}
                </tbody>
            </table>
        </div>
    );

    const activeContent = (
        <div className="space-y-4 animate-[fadeIn_0.25s_ease-in-out]">
            <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-4 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                <div className="space-y-2">
                    <div className="inline-flex items-center gap-2 text-sm text-[#7dd3fc]">
                        <CalendarClock className="w-4 h-4" />
                        Актив по текущей неделе
                    </div>
                    <div className="text-2xl font-semibold text-white">
                        {formatWeekRange(currentWeek?.week_start, currentWeek?.week_end)}
                    </div>
                </div>

                <div className="flex flex-wrap gap-3 items-center">
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
                        <input
                            value={weeklySearch}
                            onChange={(event) => setWeeklySearch(event.target.value)}
                            placeholder="Поиск по нику или PR ID"
                            className="w-72 max-w-[72vw] rounded-xl border border-white/10 bg-black/20 py-2.5 pl-10 pr-3 text-sm text-white outline-none placeholder:text-white/30 focus:border-sky-500/40"
                        />
                    </div>
                    <button
                        type="button"
                        onClick={() => void fetchActiveWeek()}
                        className="inline-flex items-center gap-2 rounded-xl border border-sky-500/20 bg-sky-500/10 px-4 py-2.5 text-sm font-medium text-sky-100 transition hover:bg-sky-500/15"
                    >
                        <RefreshCw className="w-4 h-4" />
                        Обновить
                    </button>
                </div>
            </div>

            {activeLoading ? (
                <div className="flex items-center justify-center h-64">
                    <div className="text-white/60">Загрузка...</div>
                </div>
            ) : (
                <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden">
                    <table className="w-full table-fixed text-sm border-collapse">
                        <colgroup>
                            <col className="w-[19%]" />
                            <col className="w-[8.5%]" />
                            <col className="w-[8.5%]" />
                            <col className="w-[8.5%]" />
                            <col className="w-[8.5%]" />
                            <col className="w-[8.5%]" />
                            <col className="w-[8.5%]" />
                            <col className="w-[8.5%]" />
                            <col className="w-[21.5%]" />
                        </colgroup>
                        <thead className="sticky top-0 z-20 bg-[#1f1f1f]">
                            <tr className="border-b border-white/10">
                                <th className="px-4 py-4 text-left text-xs font-semibold uppercase tracking-[0.16em] text-white/45">
                                    Ассистент
                                </th>
                                {(currentWeek?.day_labels ?? []).map((day) => (
                                    <th
                                        key={day.work_date}
                                        className="px-2 py-4 text-left text-xs font-semibold uppercase tracking-[0.16em] text-white/45"
                                    >
                                        <div className="space-y-1">
                                            <div>{day.label}</div>
                                            <div className="text-[11px] font-medium tracking-normal text-white/25">{day.work_date.slice(8, 10)}.{day.work_date.slice(5, 7)}</div>
                                        </div>
                                    </th>
                                ))}
                                <th className="px-3 py-4 text-left text-xs font-semibold uppercase tracking-[0.16em] text-white/45">
                                    Итоги недели
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {weeklyItems.length === 0 ? (
                                <tr>
                                    <td colSpan={9} className="text-center py-14 text-white/40">
                                        Ничего не найдено
                                    </td>
                                </tr>
                            ) : (
                                weeklyItems.map((assistant) => (
                                    <tr
                                        key={assistant.assistant_id}
                                        className="border-b border-white/5 align-top hover:bg-white/[0.03] transition-colors"
                                    >
                                        <td className="px-4 py-4">
                                            <div
                                                className="flex items-start gap-3 cursor-pointer group"
                                                onClick={() => navigate(`/assistants/${assistant.assistant_id}`)}
                                                title="Перейти в профиль"
                                            >
                                                <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-sky-500/80 to-cyan-400/70 flex items-center justify-center text-white font-bold text-sm shadow-[0_8px_24px_rgba(56,189,248,0.2)]">
                                                    {(assistant.nickname?.charAt(0) || '?').toUpperCase()}
                                                </div>
                                                <div className="min-w-0 space-y-1">
                                                    <div className="font-semibold text-white group-hover:text-sky-300 transition-colors truncate">
                                                        {assistant.nickname}
                                                    </div>
                                                    <span className={`inline-flex w-fit items-center px-2.5 py-1 rounded-full text-xs font-medium border ${getRoleTone(assistant.role)}`}>
                                                        {getRoleLabel(assistant.role)}
                                                    </span>
                                                </div>
                                            </div>
                                        </td>
                                        {assistant.days.map((day) => (
                                            <td key={`${assistant.assistant_id}-${day.work_date}`} className="px-2 py-3 align-top">
                                                <div className="rounded-2xl border border-white/8 bg-white/[0.025] p-3">
                                                    <div className="flex items-start justify-between gap-2">
                                                        <div className="text-[15px] font-semibold tabular-nums text-white">
                                                            {formatWeeklyHours(day.spec_hours_on_day)}
                                                        </div>
                                                        {day.resolved_status ? (
                                                            <span className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${getDayStatusTone(day.resolved_status)}`}>
                                                                {getDayStatusLabel(day.resolved_status)}
                                                            </span>
                                                        ) : null}
                                                    </div>
                                                    <div className="mt-3 grid grid-cols-2 gap-2 border-t border-white/6 pt-2.5 text-[11px]">
                                                        <div className="rounded-lg bg-black/15 px-2 py-1.5">
                                                            <div className="text-[9px] uppercase tracking-[0.12em] text-white/30">M-chat</div>
                                                            <div className="mt-1 text-sm font-semibold tabular-nums text-white">{day.mchat_count}</div>
                                                        </div>
                                                        <div className="rounded-lg bg-black/15 px-2 py-1.5">
                                                            <div className="text-[9px] uppercase tracking-[0.12em] text-white/30">Жалобы</div>
                                                            <div className="mt-1 text-sm font-semibold tabular-nums text-white">{day.complaints_count}</div>
                                                        </div>
                                                    </div>
                                                </div>
                                            </td>
                                        ))}
                                        <td className="px-3 py-3 align-top">
                                            <div className="rounded-2xl border border-white/8 bg-gradient-to-br from-sky-500/[0.08] via-sky-500/[0.02] to-transparent p-3.5 text-white">
                                                <div className="text-[10px] uppercase tracking-[0.16em] text-sky-100/50">
                                                    Итоги
                                                </div>
                                                <div className="mt-2 flex items-end justify-between gap-3">
                                                    <div>
                                                        <div className="text-[9px] uppercase tracking-[0.12em] text-white/35">Слежка</div>
                                                        <div className="mt-1 text-[22px] font-semibold leading-none tabular-nums text-white">
                                                            {formatWeeklyHours(assistant.total_spec_hours)}
                                                        </div>
                                                    </div>
                                                    <div className="rounded-full border border-rose-500/20 bg-rose-500/10 px-2.5 py-1 text-[11px] font-medium text-rose-100">
                                                        П {assistant.count_P}
                                                    </div>
                                                </div>
                                                <div className="mt-3 grid grid-cols-2 gap-2 border-t border-white/8 pt-3">
                                                    <div className="rounded-xl bg-black/15 px-3 py-2">
                                                        <div className="text-[9px] uppercase tracking-[0.12em] text-white/35">M-chat</div>
                                                        <div className="mt-1 text-sm font-semibold tabular-nums text-white">
                                                            {assistant.total_mchat}
                                                        </div>
                                                    </div>
                                                    <div className="rounded-xl bg-black/15 px-3 py-2">
                                                        <div className="text-[9px] uppercase tracking-[0.12em] text-white/35">Жалобы</div>
                                                        <div className="mt-1 text-sm font-semibold tabular-nums text-white">
                                                            {assistant.total_complaints}
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );

    if (error) {
        return (
            <div className="space-y-6 animate-[fadeIn_0.35s_ease-in-out] -mx-[calc(50vw-50%)] px-6 lg:px-12 pr-10 lg:pr-16">
                <div>
                    <h2 className="text-3xl font-bold flex items-center gap-2">
                        <span className="w-1 h-8 bg-[#3b82f6] rounded-full inline-block"></span>
                        Таблица PR Ассистентов
                    </h2>
                </div>
                <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-8 text-center text-white/50">
                    {error}
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-6 animate-[fadeIn_0.35s_ease-in-out] -mx-[calc(50vw-50%)] px-6 lg:px-12 pr-10 lg:pr-16">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                <div>
                    <h2 className="text-3xl font-bold flex items-center gap-2">
                        <span className="w-1 h-8 bg-[#3b82f6] rounded-full inline-block"></span>
                        Таблица PR Ассистентов
                    </h2>
                </div>
                <div className="text-white/60">
                    Всего: <span className="text-[#3b82f6] font-bold">{assistants.length}</span>
                </div>
            </div>

            <div className="flex gap-2 border-b border-white/10 pb-2">
                <Link
                    to="/assistants"
                    className={`px-6 py-3 rounded-t-lg font-semibold transition-all ${activeTab === 'stats'
                        ? 'bg-white/10 text-white border-b-2 border-blue-500'
                        : 'text-white/60 hover:text-white hover:bg-white/5'
                        }`}
                >
                    Статистика
                </Link>
                <Link
                    to="/assistants?tab=active"
                    className={`px-6 py-3 rounded-t-lg font-semibold transition-all ${activeTab === 'active'
                        ? 'bg-white/10 text-white border-b-2 border-sky-500'
                        : 'text-white/60 hover:text-white hover:bg-white/5'
                        }`}
                >
                    Актив
                </Link>
            </div>

            {activeTab === 'stats' ? statsContent : activeContent}
        </div>
    );
}

export default PRStats;
