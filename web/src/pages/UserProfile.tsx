import { useState, useEffect } from 'react';
import { User, Clock, Shield, History, ArrowLeft, Wifi, Calendar, Coins, BadgePercent, type LucideIcon } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import type { Assistant, AssistantLog } from '../types/domain';
import { unwrapApiData } from '../types/api';
import { formatMskToLocal } from '../utils/datetime';

export default function UserProfile() {
    const navigate = useNavigate();
    const { id } = useParams();
    const [user, setUser] = useState<Assistant | null>(null);
    const [logs, setLogs] = useState<AssistantLog[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchAssistantData = async (targetId: string | number) => {
        const assistantRes = await fetch(`/api/assistants/${targetId}`);
        if (!assistantRes.ok) {
            return null;
        }
        const json = await assistantRes.json() as unknown;
        return unwrapApiData<Assistant>(json);
    };

    const fetchAssistantLogs = async (prId: string | number) => {
        const logsRes = await fetch(`/api/assistants/${prId}/logs`);
        if (!logsRes.ok) {
            return [];
        }
        const logsJson = await logsRes.json() as unknown;
        const logsData = unwrapApiData<AssistantLog[]>(logsJson);
        return Array.isArray(logsData) ? logsData : [];
    };

    useEffect(() => {
        const fetchData = async () => {
            try {
                const token = localStorage.getItem('access_token');
                if (!token) {
                    navigate('/login');
                    return;
                }

                // 1. Check Auth (we always need to be logged in)
                const authRes = await fetch('/api/auth/me', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });

                if (authRes.status === 401) {
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('refresh_token');
                    localStorage.removeItem('user');
                    navigate('/login');
                    return;
                }

                if (!authRes.ok) throw new Error('Failed to load user info');

                // 2. Target ID must be present in the new route design (/assistants/:id)
                const targetId = id;
                if (!targetId) {
                    setError('ID профиля не указан в URL.');
                    setLoading(false);
                    return;
                }

                let assistantData: Assistant | null = null;

                try {
                    assistantData = await fetchAssistantData(targetId);
                } catch (e) {
                    console.warn("Failed to fetch assistant data", e);
                }

                if (assistantData) {
                    setUser(assistantData);
                    // 3. Fetch Logs
                    const assistantLogs = await fetchAssistantLogs(assistantData.pr_id);
                    setLogs(assistantLogs);
                } else {
                    setError('PR-профиль не найден. Возможно, ваш Discord ID не привязан к базе ассистентов.');
                }

            } catch (e: unknown) {
                console.error(e);
                setError('Ошибка загрузки данных профиля');
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, [navigate, id]);

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
        const bg = isFree ? 'bg-[#4ade80]/15 border-[#4ade80]/30' : 'bg-[#facc15]/15 border-[#facc15]/30';
        const StatusIcon = isFree ? Shield : (user.assigned_to_type === 'streamer' ? Wifi : Calendar);
        const assignedLabel = !isFree
            ? `${user.assigned_to_type === 'streamer' ? 'Стример' : 'Событие'}: ${user.assigned_to_name || 'Не указано'}`
            : 'Без закрепления';

        return (
            <div className="flex flex-col gap-3 p-4 rounded-2xl border border-white/5 bg-[#242424]/40 h-full">
                <div className="flex items-center justify-between gap-2">
                    <span className="text-white/40 text-xs font-medium uppercase tracking-wider">Текущий статус</span>
                    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-semibold ${bg} ${color}`}>
                        <StatusIcon className="w-3.5 h-3.5" />
                        <span>{isFree ? 'Свободен' : 'Закреплен'}</span>
                    </div>
                </div>
                <div className="text-sm text-white/60 truncate">
                    {assignedLabel}
                </div>
            </div>
        );
    };

    interface StatCardProps {
        label: string;
        value: string | number;
        sub?: string;
        icon: LucideIcon;
        color: string;
        valueClassName?: string;
        subClassName?: string;
    }

    const StatCard = ({
        label,
        value,
        sub,
        icon: Icon,
        color,
        valueClassName = 'text-white',
        subClassName = 'text-white/50',
    }: StatCardProps) => (
        <div className="flex flex-col gap-1 p-4 rounded-2xl border border-white/5 bg-[#242424]/40 h-full">
            <div className="flex items-center gap-2 mb-2">
                <div className={`p-1.5 rounded-lg bg-white/5 ${color}`}>
                    <Icon className="w-4 h-4" />
                </div>
                <span className="text-white/40 text-xs font-medium uppercase tracking-wider">{label}</span>
            </div>
            <div>
                <div className={`text-xl font-bold ${valueClassName}`}>{value}</div>
                {sub && <div className={`text-sm mt-1 ${subClassName}`}>{sub}</div>}
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
                                {user.appointed_at && (
                                    <div className="flex items-center gap-1.5 text-white/40 text-sm">
                                        <span className="w-1 h-1 rounded-full bg-white/40"></span>
                                        <Calendar className="w-4 h-4" />
                                        <span>Назначен: {formatMskToLocal(user.appointed_at, { day: '2-digit', month: '2-digit', year: 'numeric' })}</span>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Stats Grid integrated into Header */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 max-w-5xl">
                            <StatusBadge />

                            <StatCard
                                label="Отработано"
                                value={`${user.total_spec_hours ?? 0}ч`}
                                color="text-blue-400"
                                icon={Clock}
                            />

                            <StatCard
                                label="Общие баллы"
                                value={(user.total_points ?? 0).toFixed(2)}
                                color="text-blue-400"
                                icon={Coins}
                                valueClassName="text-blue-400"
                            />

                            <StatCard
                                label="После санкций"
                                value={(user.display_points ?? user.total_points ?? 0).toFixed(2)}
                                color="text-green-400"
                                icon={Coins}
                                valueClassName="text-green-400"
                            />

                            <StatCard
                                label="Выговоры"
                                value={user.warnings_display ?? '0/2 0/2'}
                                color="text-rose-400"
                                icon={Shield}
                            />

                            <StatCard
                                label="Штрафные баллы"
                                value={user.penalty_points ?? 0}
                                color="text-amber-400"
                                icon={Coins}
                                valueClassName="text-amber-300"
                            />

                            <StatCard
                                label="Штраф, %"
                                value={`${user.penalty_percent ?? 0}%`}
                                color="text-amber-400"
                                icon={BadgePercent}
                                valueClassName="text-amber-300"
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
                                        {log.duration && (
                                            <p className="text-xs text-white/40 mt-0.5">
                                                Время закрепления: {log.duration}
                                            </p>
                                        )}
                                    </div>

                                    <div className="text-sm text-white/30 font-mono">
                                        {formatMskToLocal(log.created_at, {
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
