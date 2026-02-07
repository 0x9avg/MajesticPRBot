import React from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { Users, Wifi, Activity, Radio, FileText, ShieldAlert, Bot, ChevronDown, ArrowRight } from 'lucide-react';

export function MainHub() {
    const navigate = useNavigate();
    const { user } = useOutletContext<any>() || {};
    const userRole = user?.role;

    // Collapsible states
    const [isMenuOpen, setIsMenuOpen] = React.useState(true);
    const [isAdminOpen, setIsAdminOpen] = React.useState(true);

    const [dashboardStats, setDashboardStats] = React.useState({
        assigned_pr_count: 0,
        unassigned_media_count: 0,
        events_today_count: 0
    });

    React.useEffect(() => {
        const fetchStats = async () => {
            try {
                const response = await fetch('/api/stats/dashboard');
                if (response.ok) {
                    const json = await response.json();
                    const data = json.data || json;
                    setDashboardStats(data);
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
        }
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

            <div className="select-none">
                <h2
                    className="text-2xl font-bold mb-6 flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity"
                    onClick={() => setIsMenuOpen(!isMenuOpen)}
                >
                    <span className="w-1 h-8 bg-[#3b82f6] rounded-full inline-block"></span>
                    Меню
                    <div className={`ml-auto p-2 rounded-full bg-white/5 transition-transform duration-300 ${isMenuOpen ? 'rotate-180' : ''}`}>
                        <ChevronDown className="w-5 h-5 text-white/60" />
                    </div>
                </h2>
                <div className={`grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 transition-all duration-300 ${isMenuOpen ? 'opacity-100' : 'opacity-0 h-0 overflow-hidden'}`}>
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

            {(userRole === 'manager' || userRole === 'developer') && (
                <div className="select-none">
                    <h2
                        className="text-2xl font-bold mb-6 flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity"
                        onClick={() => setIsAdminOpen(!isAdminOpen)}
                    >
                        <span className="w-1 h-8 bg-[#e81c5a] rounded-full inline-block"></span>
                        Управление
                        <div className={`ml-auto p-2 rounded-full bg-white/5 transition-transform duration-300 ${isAdminOpen ? 'rotate-180' : ''}`}>
                            <ChevronDown className="w-5 h-5 text-white/60" />
                        </div>
                    </h2>
                    <div className={`grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 transition-all duration-300 ${isAdminOpen ? 'opacity-100' : 'opacity-0 h-0 overflow-hidden'}`}>
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
            )}
        </div>
    );
}

export default MainHub;
