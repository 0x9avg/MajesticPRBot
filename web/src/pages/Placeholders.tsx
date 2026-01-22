import React from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import {
    Radio,
    Users,
    FileText,
    CalendarPlus,
    ShieldAlert,
    Bot,
    ArrowRight,
    Activity,
    Wifi,
    ChevronUp,
    ChevronDown
} from 'lucide-react';

export function MainHub() {
    const navigate = useNavigate();
    const [dashboardStats, setDashboardStats] = React.useState({
        assigned_pr_count: 0,
        unassigned_media_count: 0,
        events_today_count: 0
    });

    React.useEffect(() => {
        const fetchStats = async () => {
            try {
                const response = await fetch('/api/stats/dashboard');
                const result = await response.json();
                if (result.success) {
                    setDashboardStats(result.data);
                }
            } catch (error) {
                console.error('Failed to fetch dashboard stats:', error);
            }
        };

        fetchStats();
        // Poll stats every 10 seconds
        const interval = setInterval(fetchStats, 10000);
        return () => clearInterval(interval);
    }, []);

    const stats = [
        {
            label: 'Кол-во занятых PR',
            value: dashboardStats.assigned_pr_count,
            color: 'text-[#3b82f6]',
            icon: Users
        },
        {
            label: 'Медиа без закрепа',
            value: dashboardStats.unassigned_media_count,
            color: dashboardStats.unassigned_media_count === 0 ? 'text-white' : 'text-[#e81c5a]',
            icon: Wifi
        },
        {
            label: 'Мероприятий сегодня',
            value: dashboardStats.events_today_count,
            color: 'text-white',
            icon: Activity
        },
    ];

    const categories = [
        {
            title: 'Медиа',
            desc: 'Управление стримерами и контентом',
            path: '/media',
            icon: Radio,
            color: 'from-blue-500/20 to-blue-600/5 hover:border-blue-500/50'
        },
        {
            title: 'Таблица пиаров',
            desc: 'Статистика работы сотрудников',
            path: '/pr-stats',
            icon: Users,
            color: 'from-purple-500/20 to-purple-600/5 hover:border-purple-500/50'
        },
        {
            title: 'Логи',
            desc: 'История наблюдений и отчеты',
            path: '/logs',
            icon: FileText,
            color: 'from-emerald-500/20 to-emerald-600/5 hover:border-emerald-500/50'
        },
        {
            title: 'События',
            desc: 'Регистрация новых событий',
            path: '/events/new',
            icon: CalendarPlus,
            color: 'from-orange-500/20 to-orange-600/5 hover:border-orange-500/50'
        },
    ];

    const adminCategories = [
        {
            title: 'Админ-панель',
            desc: 'Управление доступом и настройками',
            path: '/admin',
            icon: ShieldAlert,
            color: 'from-red-500/20 to-red-600/5 hover:border-red-500/50 text-red-400'
        },
        {
            title: 'Bot Dashboard',
            desc: 'Состояние и логи бота',
            path: '/bot',
            icon: Bot,
            color: 'from-gray-500/20 to-gray-600/5 hover:border-gray-500/50'
        },
    ];

    return (
        <div className="space-y-12 animate-[fadeIn_0.5s_ease-in-out]">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {stats.map((stat, i) => (
                    <div key={i} className="select-none bg-[#242424]/50 backdrop-blur-sm border border-white/5 p-6 rounded-2xl flex items-center justify-between group hover:border-white/10 transition-all">
                        <div>
                            <p className="text-white/40 text-sm font-medium mb-1">{stat.label}</p>
                            <p className={`text-4xl font-bold ${stat.color}`}>{stat.value}</p>
                        </div>
                        <div className={`p-3 rounded-xl bg-white/5 ${stat.color.replace('text', 'text').replace('text-', 'text-opacity-80')}`}>
                            <stat.icon className="w-8 h-8 opacity-80" />
                        </div>
                    </div>
                ))}
            </div>

            <div>
                <h2 className="text-2xl font-bold mb-6 flex items-center gap-2">
                    <span className="w-1 h-8 bg-[#3b82f6] rounded-full inline-block"></span>
                    Меню
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                    {categories.map((cat, i) => (
                        <div
                            key={i}
                            onClick={() => navigate(cat.path)}
                            className={`relative group cursor-pointer overflow-hidden p-6 rounded-3xl border border-white/5 bg-gradient-to-br ${cat.color} transition-all duration-300 hover:scale-[1.02] hover:shadow-xl`}
                        >
                            <div className="relative z-10 flex flex-col h-full">
                                <div className="mb-4 p-3 bg-white/10 rounded-2xl w-fit">
                                    <cat.icon className="w-8 h-8 text-white" />

                                </div>
                                <h3 className="text-xl font-bold text-white mb-2">{cat.title}</h3>
                                <p className="text-white/60 text-sm flex-1">{cat.desc}</p>

                                <div className="mt-4 flex justify-end">
                                    <ArrowRight className="w-6 h-6 text-white/40 group-hover:text-white group-hover:translate-x-1 transition-all" />
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            <div>
                <h2 className="text-2xl font-bold mb-6 flex items-center gap-2">
                    <span className="w-1 h-8 bg-[#e81c5a] rounded-full inline-block"></span>
                    Управление
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                    {adminCategories.map((cat, i) => (
                        <div
                            key={i}
                            onClick={() => navigate(cat.path)}
                            className={`relative group cursor-pointer overflow-hidden p-6 rounded-3xl border border-white/5 bg-gradient-to-br ${cat.color} transition-all duration-300 hover:scale-[1.02] hover:shadow-xl`}
                        >
                            <div className="relative z-10 flex flex-col h-full">
                                <div className="mb-4 p-3 bg-white/10 rounded-2xl w-fit">
                                    <cat.icon className="w-8 h-8 text-white" />
                                </div>
                                <h3 className="text-xl font-bold text-white mb-2">{cat.title}</h3>
                                <p className="text-white/60 text-sm flex-1">{cat.desc}</p>

                                <div className="mt-4 flex justify-end">
                                    <ArrowRight className="w-6 h-6 text-white/40 group-hover:text-white group-hover:translate-x-1 transition-all" />
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

export function MediaList() { return <h2 className="text-3xl font-bold">Список медиа</h2>; }
export function PRStats() {
    const [assistants, setAssistants] = React.useState<any[]>([]);
    const [loading, setLoading] = React.useState(true);
    const [sortConfig, setSortConfig] = React.useState<{ key: string, direction: 'asc' | 'desc' }>({ key: 'role', direction: 'desc' });

    React.useEffect(() => {
        fetchAssistants();
        // Auto-refresh every 5 seconds to show changes immediately
        const interval = setInterval(fetchAssistants, 5000);
        return () => clearInterval(interval);
    }, []);

    const fetchAssistants = async () => {
        try {
            const response = await fetch('/api/assistants');
            const result = await response.json();
            if (result.success) {
                setAssistants(result.data);
            }
        } catch (error) {
            console.error('Failed to fetch assistants:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleSort = (key: string) => {
        let direction: 'asc' | 'desc' = 'asc';
        if (sortConfig.key === key && sortConfig.direction === 'asc') {
            direction = 'desc';
        }
        setSortConfig({ key, direction });
    };

    const getSortedAssistants = () => {
        const sorted = [...assistants];
        sorted.sort((a, b) => {
            if (sortConfig.key === 'role') {
                const roleWeights = {
                    'developer': 4,
                    'manager': 3,
                    'senior_employee': 2,
                    'employee': 1
                };
                const weightA = roleWeights[a.role as keyof typeof roleWeights] || 0;
                const weightB = roleWeights[b.role as keyof typeof roleWeights] || 0;
                return sortConfig.direction === 'asc' ? weightA - weightB : weightB - weightA;
            }

            if (a[sortConfig.key] < b[sortConfig.key]) {
                return sortConfig.direction === 'asc' ? -1 : 1;
            }
            if (a[sortConfig.key] > b[sortConfig.key]) {
                return sortConfig.direction === 'asc' ? 1 : -1;
            }
            return 0;
        });
        return sorted;
    };

    const getRoleBadge = (role: string) => {
        const styles = {
            developer: 'bg-red-500/20 text-red-400 border-red-500/30',
            manager: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
            senior_employee: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
            employee: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
        };

        const labels = {
            developer: 'Разработчик',
            manager: 'Менеджер',
            senior_employee: 'Ст. сотрудник',
            employee: 'Сотрудник',
        };

        return (
            <span className={`px-3 py-1 rounded-full text-xs font-medium border ${styles[role as keyof typeof styles]}`}>
                {labels[role as keyof typeof labels]}
            </span>
        );
    };

    const getStatusBadge = (assistant: any) => {
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

    const renderHeader = (label: string, sortKey: string) => (
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
                                            <div className="flex items-center gap-2">
                                                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[#3b82f6] to-[#e81c5a] flex items-center justify-center text-white font-bold text-sm">
                                                    {assistant.nickname.charAt(0).toUpperCase()}
                                                </div>
                                                <span className="font-medium text-white">{assistant.nickname}</span>
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

export function SpectateLogs() { return <h2 className="text-3xl font-bold">Логи спека</h2>; }
export function CreateEvent() { return <h2 className="text-3xl font-bold">Регистрация МП</h2>; }
export function AdminPanel() {
    return (
        <div>
            <h2 className="text-3xl font-bold mb-6">Админ-панель</h2>
            <div className="bg-[#e81c5a]/10 border border-[#e81c5a]/20 p-4 rounded-xl text-[#e81c5a] mb-6">
                🔒 Restricted Area
            </div>
            <Outlet />
        </div>
    );
}
export function BotDashboard() { return <h2 className="text-3xl font-bold">Bot Dashboard</h2>; }
