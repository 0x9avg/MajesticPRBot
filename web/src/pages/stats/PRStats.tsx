import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronUp, ChevronDown } from 'lucide-react';
import type { Assistant } from '../../types/domain';
import { unwrapApiData } from '../../types/api';

type SortKey =
    | 'nickname'
    | 'role'
    | 'experience_days'
    | 'status'
    | 'total_spec_seconds'
    | 'session_count';

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
            const response = await fetch('/api/assistants');
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
                return assistant.status || '';
            case 'total_spec_seconds':
                return assistant.total_spec_seconds || 0;
            case 'session_count':
                return assistant.session_count || 0;
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
            <span className={`px-3 py-1 rounded-full text-xs font-medium border ${style}`}>
                {label}
            </span>
        );
    };

    const getStatusBadge = (assistant: Assistant) => {
        if (assistant.status === 'free') {
            return <span className="px-3 py-1 rounded-full text-xs font-medium bg-green-500/20 text-green-400 border border-green-500/30">Свободен</span>;
        }

        const typeLabel = assistant.assigned_to_type === 'streamer' ? '🎥 Стример' : '🎉 Ивент';
        return (
            <div className="flex flex-col gap-1">
                <span className="px-3 py-1 rounded-full text-xs font-medium bg-purple-500/20 text-purple-400 border border-purple-500/30">
                    В закрепе
                </span>
                <span className="text-xs text-white/50">
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
            className="text-left p-4 text-sm font-semibold text-white/60 select-none cursor-pointer hover:text-white transition-colors group"
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
                    Таблица пиаров
                </h2>
                <div className="text-white/60">
                    Всего: <span className="text-[#3b82f6] font-bold">{assistants.length}</span>
                </div>
            </div>

            <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="w-full">
                        <thead>
                            <tr className="border-b border-white/5">
                                {renderHeader('Ник', 'nickname')}
                                {renderHeader('Должность', 'role')}
                                {renderHeader('Стаж', 'experience_days')}
                                {renderHeader('Статус', 'status')}
                                {renderHeader('Время спека', 'total_spec_seconds')}
                                {renderHeader('Сессий', 'session_count')}
                            </tr>
                        </thead>
                        <tbody>
                            {assistants.length === 0 ? (
                                <tr>
                                    <td colSpan={6} className="text-center py-12 text-white/40 select-none">
                                        Нет данных
                                    </td>
                                </tr>
                            ) : (
                                getSortedAssistants().map((assistant) => (
                                    <tr
                                        key={assistant.pr_id}
                                        className="border-b border-white/5 hover:bg-white/5 transition-colors"
                                    >
                                        <td className="p-4">
                                            <div
                                                className="flex items-center gap-2 cursor-pointer group"
                                                onClick={() => navigate(`/profile/${assistant.pr_id}`)}
                                                title="Перейти в профиль"
                                            >
                                                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[#3b82f6] to-[#e81c5a] flex items-center justify-center text-white font-bold text-sm">
                                                    {(assistant.nickname?.charAt(0) || '?').toUpperCase()}
                                                </div>
                                                <span className="font-medium text-white group-hover:text-[#3b82f6] transition-colors">{assistant.nickname}</span>
                                            </div>
                                        </td>
                                        <td className="p-4">{getRoleBadge(assistant.role)}</td>
                                        <td className="p-4 text-white/80">
                                            {assistant.experience_days} {assistant.experience_days === 1 ? 'день' : 'дней'}
                                        </td>
                                        <td className="p-4">{getStatusBadge(assistant)}</td>
                                        <td className="p-4 text-white/80 font-mono">
                                            {assistant.total_spec_hours}ч
                                        </td>
                                        <td className="p-4 text-white/80">
                                            {assistant.session_count}
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
