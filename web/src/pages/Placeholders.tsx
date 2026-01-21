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
    Wifi
} from 'lucide-react';

export function MainHub() {
    const navigate = useNavigate();

    const stats = [
        { label: 'Активных сотрудников', value: '12', color: 'text-[#3b82f6]', icon: Users },
        { label: 'Медиа онлайн', value: '8', color: 'text-[#e81c5a]', icon: Wifi },
        { label: 'Мероприятий сегодня', value: '3', color: 'text-white', icon: Activity },
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
            title: 'Логи спека',
            desc: 'История наблюдений и отчеты',
            path: '/logs',
            icon: FileText,
            color: 'from-emerald-500/20 to-emerald-600/5 hover:border-emerald-500/50'
        },
        {
            title: 'Мероприятия',
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
                    <div key={i} className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 p-6 rounded-2xl flex items-center justify-between group hover:border-white/10 transition-all">
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
export function PRStats() { return <h2 className="text-3xl font-bold">Таблица пиаров</h2>; }
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
