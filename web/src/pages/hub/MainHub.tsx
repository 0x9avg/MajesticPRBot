import React from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { Users, Wifi, Activity, Radio, FileText, ShieldAlert, Bot, ChevronDown, ArrowRight, MapPin, CalendarDays, Settings, Trash2 } from 'lucide-react';
import type { OutletUserContext } from '../../types/auth';
import type { DashboardStats, Event, EventParticipant, Streamer, StreamerAssignment } from '../../types/domain';
import { unwrapApiData, getApiErrorMessage } from '../../types/api';
import StreamerSettingsModal from '../media/components/StreamerSettingsModal';
import EventSettingsModal from '../media/components/EventSettingsModal';

type ActivityItem =
    | ({ type: 'event' } & Event)
    | ({ type: 'streamer' } & Streamer);

export function MainHub() {
    const navigate = useNavigate();
    const { user } = useOutletContext<OutletUserContext>();
    const userRole = user?.role;

    // Collapsible states
    const [isMenuOpen, setIsMenuOpen] = React.useState(true);
    const [isAdminOpen, setIsAdminOpen] = React.useState(true);
    const [isActivitiesOpen, setIsActivitiesOpen] = React.useState(true);

    const [dashboardStats, setDashboardStats] = React.useState<DashboardStats>({
        assigned_pr_count: 0,
        unassigned_media_count: 0,
        events_today_count: 0
    });

    const [onlineStreamers, setOnlineStreamers] = React.useState<Streamer[]>([]);
    const [activeEvents, setActiveEvents] = React.useState<Event[]>([]);
    const [selectedStreamer, setSelectedStreamer] = React.useState<Streamer | null>(null);
    const [selectedEvent, setSelectedEvent] = React.useState<Event | null>(null);
    const [claimError, setClaimError] = React.useState<string | null>(null);

    React.useEffect(() => {
        const fetchStats = async () => {
            try {
                const response = await fetch('/api/stats/dashboard');
                if (response.ok) {
                    const json = await response.json() as unknown;
                    const data = unwrapApiData<DashboardStats>(json);
                    setDashboardStats(data);
                }
            } catch (error) {
                console.error('Failed to fetch dashboard stats:', error);
            }
        };

        const fetchOnlineStreamers = async () => {
            try {
                const response = await fetch('/api/streamers?online_only=true&gta_only=true');
                if (response.ok) {
                    const json = await response.json() as unknown;
                    const data = unwrapApiData<{ streamers: Streamer[] } | Streamer[]>(json);
                    const normalized = Array.isArray(data) ? data : data.streamers;
                    setOnlineStreamers(Array.isArray(normalized) ? normalized : []);
                }
            } catch (error) {
                console.error('Failed to fetch online streamers:', error);
            }
        };

        const fetchActiveEvents = async () => {
            try {
                const response = await fetch('/api/events/active');
                if (response.ok) {
                    const json = await response.json() as unknown;
                    const data = unwrapApiData<Event[]>(json);
                    setActiveEvents(Array.isArray(data) ? data : []);
                }
            } catch (error) {
                console.error('Failed to fetch active events:', error);
            }
        };

        const fetchAll = () => {
            void fetchStats();
            void fetchOnlineStreamers();
            void fetchActiveEvents();
        };

        fetchAll();
        const interval = setInterval(fetchAll, 10000);
        return () => clearInterval(interval);
    }, []);

    const fetchOnlineStreamersManual = async () => {
        try {
            const response = await fetch('/api/streamers?online_only=true&gta_only=true');
            if (response.ok) {
                const json = await response.json() as unknown;
                const data = unwrapApiData<{ streamers: Streamer[] } | Streamer[]>(json);
                const normalized = Array.isArray(data) ? data : data.streamers;
                setOnlineStreamers(Array.isArray(normalized) ? normalized : []);
            }
        } catch (error) {
            console.error('Failed to refresh online streamers:', error);
        }
    };

    const fetchActiveEventsManual = async () => {
        try {
            const response = await fetch('/api/events/active');
            if (response.ok) {
                const json = await response.json() as unknown;
                const data = unwrapApiData<Event[]>(json);
                setActiveEvents(Array.isArray(data) ? data : []);
            }
        } catch (error) {
            console.error('Failed to refresh active events:', error);
        }
    };

    const handleClaimStreamer = async (streamerId: string, isProbation: boolean) => {
        if (!user?.discord_id) return;
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch('/api/spec/claim', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ streamer_id: streamerId, pr_id: user.discord_id, is_probation: isProbation })
            });
            if (response.ok) {
                setClaimError(null);
                await fetchOnlineStreamersManual();
            } else {
                const error = await response.json().catch(() => ({} as unknown));
                setClaimError(getApiErrorMessage(error, 'Не удалось закрепиться'));
                setTimeout(() => setClaimError(null), 3000);
            }
        } catch (error) {
            console.error('Error claiming streamer:', error);
            setClaimError('Ошибка при закреплении');
            setTimeout(() => setClaimError(null), 3000);
        }
    };

    const handleUnclaimStreamer = async (streamerId: string) => {
        if (!user?.discord_id) return;
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch('/api/spec/unclaim', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ streamer_id: streamerId, pr_id: user.discord_id, reason: 'manual_unclaim' })
            });
            if (response.ok) {
                setClaimError(null);
                await fetchOnlineStreamersManual();
            } else {
                const error = await response.json().catch(() => ({} as unknown));
                setClaimError(getApiErrorMessage(error, 'Не удалось открепиться'));
                setTimeout(() => setClaimError(null), 3000);
            }
        } catch (error) {
            console.error('Error unclaiming streamer:', error);
            setClaimError('Ошибка при откреплении');
            setTimeout(() => setClaimError(null), 3000);
        }
    };

    const handleJoinEvent = async (eventId: number | string) => {
        if (!user?.discord_id) return;
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`/api/events/${eventId}/join`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ user_id: user.discord_id })
            });
            if (response.ok) {
                setClaimError(null);
                await fetchActiveEventsManual();
            } else {
                const error = await response.json().catch(() => ({} as unknown));
                setClaimError(getApiErrorMessage(error, 'Не удалось присоединиться к событию'));
                setTimeout(() => setClaimError(null), 3000);
            }
        } catch (error) {
            console.error('Error joining event:', error);
            setClaimError('Ошибка при присоединении');
            setTimeout(() => setClaimError(null), 3000);
        }
    };

    const handleLeaveEvent = async (eventId: number | string) => {
        if (!user?.discord_id) return;
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`/api/events/${eventId}/leave`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ user_id: user.discord_id })
            });
            if (response.ok) {
                setClaimError(null);
                await fetchActiveEventsManual();
            } else {
                const error = await response.json().catch(() => ({} as unknown));
                setClaimError(getApiErrorMessage(error, 'Не удалось покинуть событие'));
                setTimeout(() => setClaimError(null), 3000);
            }
        } catch (error) {
            console.error('Error leaving event:', error);
            setClaimError('Ошибка при выходе из события');
            setTimeout(() => setClaimError(null), 3000);
        }
    };

    const handleUpdateStreamer = async (updates: {
        priority?: number;
        pr_slots?: number;
        is_pinned?: boolean;
        allow_juniors?: boolean;
        priority_override?: number;
        pr_slots_override?: number;
    }) => {
        if (!selectedStreamer) return;
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`/api/streamers/${selectedStreamer.streamer_id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify(updates)
            });
            if (response.ok) {
                await fetchOnlineStreamersManual();
            }
        } catch (error) {
            console.error('Failed to update streamer:', error);
        }
    };

    const handleUpdateEvent = async (updates: {
        name: string;
        description: string;
        priority: number;
        is_pinned: boolean;
        required_pr_count: number;
    }) => {
        if (!selectedEvent) return;
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`/api/events/${selectedEvent.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify(updates)
            });
            if (response.ok) {
                // Refresh active events
                const evtResponse = await fetch('/api/events/active');
                if (evtResponse.ok) {
                    const json = await evtResponse.json() as unknown;
                    const data = unwrapApiData<Event[]>(json);
                    setActiveEvents(Array.isArray(data) ? data : []);
                }
            }
        } catch (error) {
            console.error('Failed to update event:', error);
        }
    };

    const handleEndEvent = async (event: Event) => {
        if (!window.confirm(`Завершить событие "${event.name}"?`)) return;
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`/api/events/${event.id}/end`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (response.ok) {
                await fetchActiveEventsManual();
            } else {
                console.error('Failed to end event', await response.text());
            }
        } catch (error) {
            console.error('Failed to end event:', error);
        }
    };

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

    // Combine events and streamers into activities
    const activities: ActivityItem[] = [
        ...activeEvents.map((event) => ({ ...event, type: 'event' } as ActivityItem)),
        ...onlineStreamers.map((streamer) => ({ ...streamer, type: 'streamer' } as ActivityItem))
    ].sort((a, b) => {
        const aPinned = a.is_pinned ? 1 : 0;
        const bPinned = b.is_pinned ? 1 : 0;
        if (aPinned !== bPinned) return bPinned - aPinned;
        return (b.priority || 0) - (a.priority || 0);
    });

    // Unified check: is the user claimed anywhere (event or streamer)?
    const isGlobalClaimed = (() => {
        if (!user?.discord_id) return false;
        const discordIdStr = String(user.discord_id);
        const inEvent = activeEvents.some(e =>
            (e.participants || []).some((p: EventParticipant) => String(p.pr_id) === discordIdStr)
        );
        const inStreamer = onlineStreamers.some(s =>
            (s.assignments || []).some((a: StreamerAssignment) => String(a.pr_id) === discordIdStr)
        );
        return inEvent || inStreamer;
    })();

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

            {/* Activities Section */}
            <div className="select-none">
                <h2
                    className="text-2xl font-bold mb-6 flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity"
                    onClick={() => setIsActivitiesOpen(!isActivitiesOpen)}
                >
                    <span className="w-1 h-8 bg-emerald-500 rounded-full inline-block"></span>
                    Активности
                    <span className="text-sm font-normal text-white/40 ml-2">
                        {activities.length > 0 ? `${activities.length}` : ''}
                    </span>
                    <div className={`ml-auto p-2 rounded-full bg-white/5 transition-transform duration-300 ${isActivitiesOpen ? 'rotate-180' : ''}`}>
                        <ChevronDown className="w-5 h-5 text-white/60" />
                    </div>
                </h2>
                <div className={`transition-all duration-300 ${isActivitiesOpen ? 'opacity-100' : 'opacity-0 h-0 overflow-hidden'}`}>
                    {activities.length === 0 ? (
                        <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-8 text-center text-white/40">
                            Нет активностей
                        </div>
                    ) : (
                        <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden p-2">
                            <div className="flex flex-col gap-1">
                                {activities.map((item) => {
                                    if (item.type === 'event') {
                                        const event = item;
                                        const participants = event.participants || [];
                                        const currentParticipants = event.current_participants || participants.length;
                                        const isUserParticipant = participants.some((p: EventParticipant) => String(p.pr_id) === String(user?.discord_id));
                                        return (
                                            <div key={`event-${event.id}`} className="group flex items-center p-3 rounded-xl hover:bg-white/5 transition-all">
                                                <div className="flex items-center gap-4 flex-1 min-w-0 mr-2">
                                                    <div className={`w-8 h-8 rounded-lg border-2 flex items-center justify-center font-bold select-none shrink-0 relative ${event.priority === 1 ? 'bg-green-500/20 text-green-400 border-green-500/30' :
                                                        event.priority === 2 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' :
                                                            event.priority === 3 ? 'bg-red-500/20 text-red-400 border-red-500/30' :
                                                                'bg-white/5 text-white/50 border-white/20'
                                                        }`}>
                                                        {event.priority}
                                                        {event.is_pinned && (
                                                            <div className="absolute -top-2 -right-2 bg-blue-500 text-white p-0.5 rounded-full shadow-lg border border-[#1e1e1e]">
                                                                <MapPin className="w-3 h-3" />
                                                            </div>
                                                        )}
                                                    </div>
                                                    <div className="w-9 h-9 rounded-lg bg-purple-500/20 flex items-center justify-center text-purple-400 shrink-0">
                                                        <CalendarDays className="w-5 h-5" />
                                                    </div>
                                                    <div className="min-w-0">
                                                        <h4 className="font-bold text-lg text-white truncate">
                                                            {event.name}
                                                            {event.start_time && (
                                                                <span className="ml-2 text-purple-400 text-sm font-medium">
                                                                    [{new Date(event.start_time).toLocaleDateString()} {new Date(event.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}]
                                                                </span>
                                                            )}
                                                        </h4>
                                                        <p className="text-sm text-white/40 truncate">{event.description}</p>
                                                    </div>
                                                </div>
                                                <div className="flex-[2] flex items-center px-4 border-l border-white/10">
                                                    <div className="flex-1">
                                                        {currentParticipants > 0 ? (
                                                            <div className="flex flex-wrap gap-2">
                                                                {participants.map((participant: EventParticipant) => (
                                                                    <span
                                                                        key={participant.pr_id}
                                                                        onClick={() => navigate(`/profile/${participant.pr_id}`)}
                                                                        className="font-bold text-blue-400 hover:text-blue-300 cursor-pointer transition-colors"
                                                                    >
                                                                        @{participant.nickname}
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            <div className="text-sm font-bold text-white/40 select-none">Ассистента нет</div>
                                                        )}
                                                    </div>
                                                    <div className="flex items-center gap-1.5 ml-2 shrink-0">
                                                        {isUserParticipant ? (
                                                            <button
                                                                onClick={(e) => { e.stopPropagation(); void handleLeaveEvent(event.id); }}
                                                                className="px-3 py-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-xs font-semibold hover:bg-red-500/20 transition-colors text-red-400 whitespace-nowrap"
                                                            >
                                                                Открепиться
                                                            </button>
                                                        ) : !isGlobalClaimed && (
                                                            <button
                                                                onClick={(e) => { e.stopPropagation(); void handleJoinEvent(event.id); }}
                                                                className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/80 whitespace-nowrap"
                                                            >
                                                                Закрепиться
                                                            </button>
                                                        )}
                                                        {(userRole === 'manager' || userRole === 'developer') && (
                                                            <>
                                                                <button
                                                                    onClick={(e) => { e.stopPropagation(); setSelectedEvent(event); }}
                                                                    className="p-1.5 hover:bg-white/5 rounded-lg text-white/40 hover:text-white transition-colors"
                                                                    title="Настройки события"
                                                                >
                                                                    <Settings className="w-4 h-4" />
                                                                </button>
                                                                <button
                                                                    onClick={(e) => { e.stopPropagation(); void handleEndEvent(event); }}
                                                                    className="p-1.5 hover:bg-red-500/10 rounded-lg text-white/40 hover:text-red-400 transition-colors"
                                                                    title="Завершить событие"
                                                                >
                                                                    <Trash2 className="w-4 h-4" />
                                                                </button>
                                                            </>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>
                                        );
                                    } else {
                                        const streamer = item;
                                        const assignments = streamer.assignments || [];
                                        const isUserClaimed = assignments.some((a: StreamerAssignment) => String(a.pr_id) === String(user?.discord_id));

                                        const effectiveSlots = streamer.pr_slots_override ?? streamer.pr_slots;
                                        // A user can claim if there are slots AND they aren't already claimed to someone else
                                        const hasSlots = assignments.length < effectiveSlots;

                                        return (
                                            <div
                                                key={`streamer-${streamer.streamer_id}`}
                                                className="group flex items-center p-3 rounded-xl hover:bg-white/5 transition-all"
                                            >
                                                <div
                                                    className="flex items-center gap-4 flex-1 min-w-0 mr-2 cursor-pointer"
                                                    onClick={() => navigate(`/media/${streamer.streamer_id}`)}
                                                >
                                                    <div className={`w-8 h-8 rounded-lg border-2 flex items-center justify-center font-bold select-none shrink-0 relative ${streamer.priority === 1 ? 'bg-green-500/20 text-green-400 border-green-500/30' :
                                                        streamer.priority === 2 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' :
                                                            streamer.priority === 3 ? 'bg-red-500/20 text-red-400 border-red-500/30' :
                                                                'bg-white/5 text-white/50 border-white/20'
                                                        }`}>
                                                        {streamer.priority_override ?? streamer.priority}
                                                        {streamer.is_pinned && (
                                                            <div className="absolute -top-2 -right-2 bg-blue-500 text-white p-0.5 rounded-full shadow-lg border border-[#1e1e1e]">
                                                                <MapPin className="w-3 h-3" />
                                                            </div>
                                                        )}
                                                    </div>
                                                    <img
                                                        src={streamer.profile_image_url || streamer.stream_thumbnail_url || undefined}
                                                        alt={streamer.streamer_name}
                                                        className="w-9 h-9 rounded-lg object-cover bg-[#121212] shrink-0"
                                                    />
                                                    <div className="min-w-0">
                                                        <h4 className="font-bold text-lg text-white truncate">
                                                            {streamer.streamer_name}
                                                            {streamer.game_name && (
                                                                <span className="ml-2 text-emerald-400 text-sm font-medium">
                                                                    {streamer.game_name}
                                                                </span>
                                                            )}
                                                        </h4>
                                                        <div className="flex items-center gap-2">
                                                            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
                                                            <span className="text-sm text-green-400">Онлайн</span>
                                                        </div>
                                                    </div>
                                                </div>
                                                <div className="flex-[2] flex items-center px-4 border-l border-white/10">
                                                    <div className="flex-1">
                                                        {assignments.length > 0 ? (
                                                            <div className="flex flex-wrap gap-2">
                                                                {assignments.map((a: StreamerAssignment) => (
                                                                    <span
                                                                        key={a.pr_id}
                                                                        onClick={(e) => {
                                                                            e.stopPropagation();
                                                                            navigate(`/profile/${a.pr_id}`);
                                                                        }}
                                                                        className={`font-bold cursor-pointer transition-colors ${a.is_probation ? 'text-green-400 hover:text-green-300' : 'text-blue-400 hover:text-blue-300'
                                                                            }`}
                                                                    >
                                                                        @{a.nickname}
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            <div className="text-sm font-bold text-white/40 select-none">Ассистента нет</div>
                                                        )}
                                                    </div>
                                                    <div className="flex items-center gap-1.5 ml-2 shrink-0">
                                                        {isUserClaimed ? (
                                                            <button
                                                                onClick={(e) => { e.stopPropagation(); void handleUnclaimStreamer(streamer.streamer_id); }}
                                                                className="px-3 py-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-xs font-semibold hover:bg-red-500/20 transition-colors text-red-400 whitespace-nowrap"
                                                            >
                                                                Открепиться
                                                            </button>
                                                        ) : hasSlots && !isGlobalClaimed && (
                                                            <>
                                                                <button
                                                                    onClick={(e) => { e.stopPropagation(); void handleClaimStreamer(streamer.streamer_id, false); }}
                                                                    className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/80 whitespace-nowrap"
                                                                >
                                                                    Закрепиться
                                                                </button>
                                                                {user?.permissions?.can_spec_probation && streamer.allow_juniors !== false && (
                                                                    <button
                                                                        onClick={(e) => { e.stopPropagation(); void handleClaimStreamer(streamer.streamer_id, true); }}
                                                                        className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/60 whitespace-nowrap"
                                                                    >
                                                                        Вторым
                                                                    </button>
                                                                )}
                                                            </>
                                                        )}
                                                        {(userRole === 'manager' || userRole === 'developer') && (
                                                            <button
                                                                onClick={(e) => { e.stopPropagation(); setSelectedStreamer(streamer); }}
                                                                className="p-1.5 hover:bg-white/5 rounded-lg text-white/40 hover:text-white transition-colors"
                                                                title="Временные настройки"
                                                            >
                                                                <Settings className="w-4 h-4" />
                                                            </button>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>
                                        );
                                    }
                                })}
                            </div>
                        </div>
                    )}

                    {/* Claim error toast */}
                    {claimError && (
                        <div className="mt-2 px-4 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm animate-[fadeIn_0.2s_ease-out]">
                            {claimError}
                        </div>
                    )}
                </div>
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

            <StreamerSettingsModal
                streamer={selectedStreamer}
                isOpen={!!selectedStreamer}
                onClose={() => setSelectedStreamer(null)}
                onSave={handleUpdateStreamer}
                mode="override"
            />
            <EventSettingsModal
                event={selectedEvent}
                isOpen={!!selectedEvent}
                onClose={() => setSelectedEvent(null)}
                onSave={handleUpdateEvent}
            />
        </div>
    );
}

export default MainHub;
