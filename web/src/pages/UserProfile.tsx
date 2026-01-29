import { useState, useEffect } from 'react';
import { User, Clock, Shield, History, ArrowLeft, Wifi, Calendar } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export default function UserProfile() {
    const navigate = useNavigate();
    const [user, setUser] = useState<any>(null);
    const [logs, setLogs] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const token = localStorage.getItem('access_token');
                if (!token) {
                    navigate('/login');
                    return;
                }

                // 1. Get Logged In User
                const authRes = await fetch('/api/auth/me', {
                    headers: { 'Authorization': `Bearer ${token} ` }
                });

                if (authRes.status === 401) {
                    localStorage.removeItem('access_token');
                    navigate('/login');
                    return;
                }

                if (!authRes.ok) throw new Error('Failed to load user info');
                const authUser = await authRes.json();

                // 2. Fetch PR Data
                // Try fetching by Discord ID first
                let assistantData = null;

                try {
                    const assistantRes = await fetch(`/api/assistants/${authUser.discord_id}`);
                    if (assistantRes.ok) {
                        const json = await assistantRes.json();
                        assistantData = json.data || json;
                    } else {
                        // Fallback: Try finding by nickname (if ID mismatch or fresh DB)
                        const allRes = await fetch('/api/assistants');
                        if (allRes.ok) {
                            const allJson = await allRes.json();
                            const allData = allJson.data || allJson;
                            assistantData = (Array.isArray(allData) ? allData : []).find((a: any) =>
                                a.nickname.toLowerCase() === authUser.nickname.toLowerCase()
                            );
                        }
                    }
                } catch (e) {
                    console.warn("Failed to fetch assistant data", e);
                }

                if (assistantData) {
                    setUser(assistantData);
                    // 3. Fetch Logs
                    const logsRes = await fetch(`/api/assistants/${assistantData.pr_id}/logs`);
                    if (logsRes.ok) {
                        const logsJson = await logsRes.json();
                        const logsData = logsJson.data || logsJson;
                        setLogs(Array.isArray(logsData) ? logsData : []);
                    }
                } else {
                    setError('PR-профиль не найден. Возможно, ваш Discord ID не привязан к базе ассистентов.');
                }

            } catch (e) {
                console.error(e);
                setError('Ошибка загрузки данных профиля');
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, [navigate]);

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="w-8 h-8 rounded-full border-2 border-white/20 border-t-[#3b82f6] animate-spin" />
            </div>
        );
    }

    if (error || !user) {
        return (
            <div className="flex flex-col items-center justify-center h-64 gap-4 animate-[fadeIn_0.5s_ease-in-out]">
                <div className="w-16 h-16 rounded-full bg-red-500/10 flex items-center justify-center text-red-400 mb-2">
                    <Shield className="w-8 h-8" />
                </div>
                <div className="text-white/60 text-lg">{error || 'Пользователь не найден'}</div>
                <button onClick={() => navigate(-1)} className="px-6 py-2 bg-white/5 hover:bg-white/10 rounded-xl text-white transition-colors">
                    Вернуться назад
                </button>
            </div>
        );
    }

    const StatusBadge = () => {
        const isFree = user.status === 'free';
        const color = isFree ? 'text-[#4ade80]' : 'text-[#facc15]';
        const bg = isFree ? 'bg-[#4ade80]/10' : 'bg-[#facc15]/10';
        const StatusIcon = isFree ? Shield : (user.assigned_to_type === 'streamer' ? Wifi : Calendar);

        return (
            <div className={`flex flex-col gap-1 p-4 rounded-2xl border border-white/5 bg-[#242424]/40 h-full`}>
                <div className="flex items-center gap-2 mb-2">
                    <div className={`p-1.5 rounded-lg ${bg} ${color}`}>
                        <StatusIcon className="w-4 h-4" />
                    </div>
                    <span className="text-white/40 text-xs font-medium uppercase tracking-wider">Текущий статус</span>
                </div>
                <div>
                    <div className={`text-xl font-bold ${color}`}>
                        {isFree ? 'Свободен' : 'В работе'}
                    </div>
                    {!isFree && (
                        <div className="text-sm text-white/50 mt-1 truncate">
                            {user.assigned_to_name}
                        </div>
                    )}
                </div>
            </div>
        );
    };

    const StatCard = ({ label, value, sub, icon: Icon, color }: any) => (
        <div className="flex flex-col gap-1 p-4 rounded-2xl border border-white/5 bg-[#242424]/40 h-full">
            <div className="flex items-center gap-2 mb-2">
                <div className={`p-1.5 rounded-lg bg-white/5 ${color}`}>
                    <Icon className="w-4 h-4" />
                </div>
                <span className="text-white/40 text-xs font-medium uppercase tracking-wider">{label}</span>
            </div>
            <div>
                <div className={`text-xl font-bold text-white`}>{value}</div>
                {sub && <div className="text-sm text-white/50 mt-1">{sub}</div>}
            </div>
        </div>
    );

    return (
        <div className="max-w-5xl mx-auto space-y-8 animate-[fadeIn_0.5s_ease-in-out]">
            {/* Header Card */}
            <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 p-8 rounded-3xl relative overflow-hidden group">
                {/* Background Effects */}
                <div className="absolute top-0 right-0 w-96 h-96 bg-gradient-to-br from-[#3b82f6]/10 to-[#e81c5a]/10 blur-[100px] pointer-events-none group-hover:opacity-75 transition-opacity duration-700" />

                <div className="relative z-10 flex flex-col md:flex-row gap-8">
                    {/* Avatar */}
                    <div className="flex-shrink-0">
                        <div className="w-32 h-32 md:w-40 md:h-40 rounded-full bg-gradient-to-br from-[#3b82f6] to-[#e81c5a] p-1 shadow-2xl shadow-blue-500/20">
                            <div className="w-full h-full rounded-full bg-[#1a1a1a] flex items-center justify-center text-4xl md:text-5xl font-bold text-white select-none">
                                {user.nickname[0].toUpperCase()}
                            </div>
                        </div>
                    </div>

                    {/* Content Column */}
                    <div className="flex-1 min-w-0">
                        {/* Top: Nick, Role, Exp */}
                        <div className="flex flex-wrap items-center gap-4 mb-8">
                            <h1 className="text-3xl md:text-4xl font-bold text-white">{user.nickname}</h1>

                            <div className="flex items-center gap-3">
                                {/* Role Badge */}
                                <div className="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-sm font-medium text-white/80">
                                    {user.role}
                                </div>
                                {/* Exp Badge */}
                                <div className="flex items-center gap-1.5 text-white/40 text-sm">
                                    <span className="w-1 h-1 rounded-full bg-white/40"></span>
                                    <User className="w-4 h-4" />
                                    <span>{user.experience_days} дней стажа</span>
                                </div>
                            </div>
                        </div>

                        {/* Stats Grid integrated into Header */}
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-3xl">
                            <StatusBadge />

                            <StatCard
                                label="Отработано"
                                value={`${user.total_spec_hours}ч`}
                                color="text-blue-400"
                                icon={Clock}
                            />

                            <StatCard
                                label="Сессий"
                                value={user.session_count}
                                color="text-purple-400"
                                icon={History}
                            />
                        </div>
                    </div>

                    <button
                        onClick={() => navigate(-1)}
                        className="absolute top-6 right-6 p-2 hover:bg-white/10 rounded-xl transition-colors text-white/40 hover:text-white"
                        title="Назад"
                    >
                        <ArrowLeft className="w-6 h-6" />
                    </button>
                </div>
            </div>

            {/* Logs Section */}
            <div className="space-y-4">
                <div className="flex items-center gap-3 px-2 mb-2 border-l-2 border-[#3b82f6] pl-4">
                    <h2 className="text-xl font-bold text-white">
                        История активности
                    </h2>
                </div>

                <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden min-h-[200px]">
                    {logs.length === 0 ? (
                        <div className="p-12 text-center flex flex-col items-center justify-center h-full gap-4">
                            <div className="w-12 h-12 rounded-full bg-white/5 flex items-center justify-center">
                                <History className="w-6 h-6 text-white/20" />
                            </div>
                            <p className="text-white/40">История действий пока пуста</p>
                        </div>
                    ) : (
                        <div className="divide-y divide-white/5">
                            {logs.map((log) => (
                                <div key={log.id} className="p-5 flex items-center gap-4 hover:bg-white/5 transition-colors group">
                                    <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${log.action.includes('Unassigned') ? 'bg-green-500/10 text-green-400' : 'bg-blue-500/10 text-blue-400'
                                        }`}>
                                        {log.action.includes('Unassigned') ? <Shield className="w-5 h-5" /> : <Wifi className="w-5 h-5" />}
                                    </div>

                                    <div className="flex-1">
                                        <p className="font-medium text-white group-hover:text-[#3b82f6] transition-colors">
                                            {log.action}
                                        </p>
                                        {log.target && (
                                            <p className="text-sm text-white/50 mt-0.5">
                                                {log.target}
                                            </p>
                                        )}
                                    </div>

                                    <div className="text-sm text-white/30 font-mono">
                                        {new Date(log.created_at).toLocaleString('ru-RU', {
                                            day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
                                        })}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
