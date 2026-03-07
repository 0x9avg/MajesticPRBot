import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronUp, ChevronDown } from 'lucide-react';
import type { Assistant } from '../../types/domain';
import { unwrapApiData } from '../../types/api';
import { apiFetch } from '../../api/client';

type SortKey =
    | 'nickname'
    | 'role'
    | 'experience_days'
    | 'status'
    | 'total_spec_hours'
    | 'avg_spec_hours_per_day_30d'
    | 'total_points'
    | 'display_points'
    | 'warnings'
    | 'penalty_points'
    | 'penalty_percent';

export function PRStats() {
    const navigate = useNavigate();
    const [assistants, setAssistants] = React.useState<Assistant[]>([]);
    const [loading, setLoading] = React.useState(true);
    const [sortConfig, setSortConfig] = React.useState<{ key: SortKey, direction: 'asc' | 'desc' }>({ key: 'role', direction: 'desc' });

    React.useEffect(() => {
        fetchAssistants();
        // Auto-refresh every 5 seconds to show changes immediately
        const interval = setInterval(fetchAssistants, 5000);
        return () => clearInterval(interval);
    }, []);

    const fetchAssistants = async () => {
        try {
            const response = await apiFetch('/api/assistants');
            if (response.ok) {
                const json = await response.json() as unknown;
                const data = unwrapApiData<Assistant[] | { assistants: Assistant[] }>(json);
                const normalized = Array.isArray(data) ? data : data.assistants;
                setAssistants(Array.isArray(normalized) ? normalized : []);
            }
        } catch (error) {
            console.error('Failed to fetch assistants:', error);
        } finally {
            setLoading(false);
        }
    };

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
            case 'total_points':
                return assistant.total_points ?? 0;
            case 'display_points':
                return assistant.display_points ?? assistant.total_points ?? 0;
            case 'penalty_points':
                return assistant.penalty_points || 0;
            case 'penalty_percent':
                return assistant.penalty_percent || 0;
            case 'warnings':
                return (assistant.strict_warnings || 0) * 10 + (assistant.oral_warnings || 0);
            default:
                return 0;
        }
    };

    const getSortedAssistants = () => {
        const sorted = [...assistants];
        sorted.sort((a, b) => {
            if (sortConfig.key === 'role') {
                const roleWeights: Record<string, number> = {
                    'developer': 4,
                    'manager': 3,
                    'senior_employee': 2,
                    'employee': 1,
                    'junior_employee': 0
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

    const penaltyPointsSortedPositive = React.useMemo(
        () =>
            assistants
                .map((assistant) => Number(assistant.penalty_points || 0))
                .filter((value) => value > 0)
                .sort((a, b) => a - b),
        [assistants]
    );

    const penaltyPercentSortedPositive = React.useMemo(
        () =>
            assistants
                .map((assistant) => Number(assistant.penalty_percent || 0))
                .filter((value) => value > 0)
                .sort((a, b) => a - b),
        [assistants]
    );

    const getRelativePenaltyClass = (
        value: number,
        sortedPositiveValues: number[]
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
        const strict = assistant.strict_warnings || 0;
        const oral = assistant.oral_warnings || 0;

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
            manager: 'Менеджер',
            senior_employee: 'Ст. сотрудник',
            employee: 'Сотрудник',
            junior_employee: 'Мл. сотрудник',
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
        return sortConfig.direction === 'asc' ? <ChevronUp className="w-4 h-4 text-[#3b82f6]" /> : <ChevronDown className="w-4 h-4 text-[#3b82f6]" />;
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

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="text-white/60">Загрузка...</div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <h2 className="text-3xl font-bold flex items-center gap-2">
                    <span className="w-1 h-8 bg-[#3b82f6] rounded-full inline-block"></span>
                    Таблица PR Ассистентов
                </h2>
                <div className="text-white/60">
                    Всего: <span className="text-[#3b82f6] font-bold">{assistants.length}</span>
                </div>
            </div>

            <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden">
                <div className="max-h-[70vh] overflow-y-auto">
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
                                {renderHeader('Общие баллы', 'total_points')}
                                {renderHeader('После санк.', 'display_points')}
                                {renderHeader('Штраф. баллы', 'penalty_points')}
                                {renderHeader('Штраф, %', 'penalty_percent')}
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
                                                ((assistant.total_spec_hours || 0) / 30)
                                            )}ч
                                        </td>
                                        <td className="p-3 whitespace-nowrap">
                                            <span className="inline-flex px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap bg-blue-500/15 text-blue-300 border-blue-500/30">
                                                {(assistant.total_points ?? 0).toFixed(2)}
                                            </span>
                                        </td>
                                        <td className="p-3 whitespace-nowrap">
                                            <span className="inline-flex px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap bg-green-500/15 text-green-300 border-green-500/30">
                                                {(assistant.display_points ?? assistant.total_points ?? 0).toFixed(2)}
                                            </span>
                                        </td>
                                        <td className="p-3 whitespace-nowrap">
                                            <span
                                                className={`inline-flex px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap ${getRelativePenaltyClass(
                                                    Number(assistant.penalty_points || 0),
                                                    penaltyPointsSortedPositive
                                                )}`}
                                            >
                                                {Number(assistant.penalty_points || 0)}
                                            </span>
                                        </td>
                                        <td className="p-3 whitespace-nowrap">
                                            <span
                                                className={`inline-flex px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap ${getRelativePenaltyClass(
                                                    Number(assistant.penalty_percent || 0),
                                                    penaltyPercentSortedPositive
                                                )}`}
                                            >
                                                {Number(assistant.penalty_percent || 0)}%
                                            </span>
                                        </td>
                                        <td className="p-3 whitespace-nowrap">
                                            <span className={`inline-flex px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap ${getWarningsBadgeClass(assistant)}`}>
                                                {assistant.warnings_display || '0/2 0/2'}
                                            </span>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}

export default PRStats;
