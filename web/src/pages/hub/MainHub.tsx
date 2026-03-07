import React from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { Users, Wifi, UserPlus, Radio, FileText, ShieldAlert, Bot, ChevronDown, ArrowRight, MapPin, CalendarDays, Settings, Trash2, Twitch, Plus, Clock } from 'lucide-react';
import type { OutletUserContext } from '../../types/auth';
import type { DashboardStats, Event, EventParticipant, Streamer, StreamerAssignment } from '../../types/domain';
import { unwrapApiData, getApiErrorMessage } from '../../types/api';
import { formatMskToLocal } from '../../utils/datetime';
import StreamerSettingsModal from '../media/components/StreamerSettingsModal';
import EventSettingsModal from '../media/components/EventSettingsModal';
import ConfirmDialog from '../../components/feedback/ConfirmDialog';
import NotificationToast from '../../components/feedback/NotificationToast';
import { useConfirmDialog, usePopupToast } from '../../components/feedback/hooks';
import { apiFetch } from '../../api/client';
import { ADMIN_SECTION_PERMISSIONS } from '../../rbac/catalog';
import { hasAny, hasPerm } from '../../rbac/guards';

type ActivityItem =
    | ({ type: 'event' } & Event)
    | ({ type: 'streamer' } & Streamer);

export function MainHub() {
    const navigate = useNavigate();
    const { user } = useOutletContext<OutletUserContext>();
    const { toast, showToast, closeToast } = usePopupToast(3000);
    const { confirm, dialogProps } = useConfirmDialog();
    const canManageStreamers = hasAny(user, ['streamers.update', 'streamers.delete']);
    const canManageEvents = hasAny(user, ['events.manage', 'events.update']);
    const canViewAdminSection = hasAny(user, ADMIN_SECTION_PERMISSIONS);
    const canViewBotDashboard = hasAny(user, ['monitoring.view', 'monitoring.refresh']);
    const canViewReturns = hasAny(user, ['returns.view', 'returns.history.view']);
    const canClaimMain = hasPerm(user, 'spec.claim.main');
    const canClaimProbation = hasPerm(user, 'spec.claim.probation');
    const canUnclaimSelf = hasPerm(user, 'spec.unclaim.self');
    const canJoinEvents = hasPerm(user, 'events.join.self');
    const canLeaveEvents = hasPerm(user, 'events.leave.self');
    const canRequestSpec = hasPerm(user, 'events.spec.request');

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

    // Spec request modal state
    const [isSpecRequestOpen, setIsSpecRequestOpen] = React.useState(false);
    const [specRequestName, setSpecRequestName] = React.useState('');
    const [specRequestDesc, setSpecRequestDesc] = React.useState('');
    const [specRequestPriority, setSpecRequestPriority] = React.useState(0);
    const [specRequestLoading, setSpecRequestLoading] = React.useState(false);

    React.useEffect(() => {
        const fetchStats = async () => {
            try {
                const response = await apiFetch('/api/stats/dashboard');
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
                const response = await apiFetch('/api/streamers?online_only=true&gta_only=true');
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
                const response = await apiFetch('/api/events/active');
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
            const response = await apiFetch('/api/streamers?online_only=true&gta_only=true');
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
            const response = await apiFetch('/api/events/active');
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
        try {
            const response = await apiFetch('/api/spec/claim', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ streamer_id: streamerId, is_probation: isProbation })
            });
            if (response.ok) {
                await fetchOnlineStreamersManual();
            } else {
                const error = await response.json().catch(() => ({} as unknown));
                showToast(getApiErrorMessage(error, 'Не удалось закрепиться'), 'error');
            }
        } catch (error) {
            console.error('Error claiming streamer:', error);
            showToast('Ошибка при закреплении', 'error');
        }
    };

    const handleUnclaimStreamer = async (streamerId: string) => {
        try {
            const response = await apiFetch('/api/spec/unclaim', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ streamer_id: streamerId, reason: 'manual_unclaim' })
            });
            if (response.ok) {
                await fetchOnlineStreamersManual();
            } else {
                const error = await response.json().catch(() => ({} as unknown));
                showToast(getApiErrorMessage(error, 'Не удалось открепиться'), 'error');
            }
        } catch (error) {
            console.error('Error unclaiming streamer:', error);
            showToast('Ошибка при откреплении', 'error');
        }
    };

    const handleJoinEvent = async (eventId: number | string) => {
        try {
            const response = await apiFetch(`/api/events/${eventId}/join`, {
                method: 'POST',
            });
            if (response.ok) {
                await fetchActiveEventsManual();
            } else {
                const error = await response.json().catch(() => ({} as unknown));
                showToast(getApiErrorMessage(error, 'Не удалось присоединиться к событию'), 'error');
            }
        } catch (error) {
            console.error('Error joining event:', error);
            showToast('Ошибка при присоединении', 'error');
        }
    };

    const handleLeaveEvent = async (eventId: number | string) => {
        try {
            const response = await apiFetch(`/api/events/${eventId}/leave`, {
                method: 'POST',
            });
            if (response.ok) {
                await fetchActiveEventsManual();
            } else {
                const error = await response.json().catch(() => ({} as unknown));
                showToast(getApiErrorMessage(error, 'Не удалось покинуть событие'), 'error');
            }
        } catch (error) {
            console.error('Error leaving event:', error);
            showToast('Ошибка при выходе из события', 'error');
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
            const response = await apiFetch(`/api/streamers/${selectedStreamer.streamer_id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
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
            const response = await apiFetch(`/api/events/${selectedEvent.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updates)
            });
            if (response.ok) {
                // Refresh active events
                const evtResponse = await apiFetch('/api/events/active');
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
        const confirmed = await confirm({
            title: 'Завершить событие?',
            message: <>Событие <span className="text-white font-semibold">{event.name}</span> будет завершено для всех участников.</>,
            confirmLabel: 'Завершить',
            tone: 'danger',
        });

        if (!confirmed) return;

        try {
            const response = await apiFetch(`/api/events/${event.id}/end`, {
                method: 'POST',
            });
            if (response.ok) {
                await fetchActiveEventsManual();
                showToast(`Событие "${event.name}" завершено`);
            } else {
                console.error('Failed to end event', await response.text());
                showToast(`Не удалось завершить событие "${event.name}"`, 'error');
            }
        } catch (error) {
            console.error('Failed to end event:', error);
            showToast(`Не удалось завершить событие "${event.name}"`, 'error');
        }
    };

    const handleCreateSpecRequest = async () => {
        if (!specRequestName.trim()) return;
        setSpecRequestLoading(true);
        try {
            const response = await apiFetch('/api/events/spec-request', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: specRequestName.trim(),
                    description: specRequestDesc.trim(),
                    priority: specRequestPriority,
                })
            });
            if (response.ok) {
                setIsSpecRequestOpen(false);
                setSpecRequestName('');
                setSpecRequestDesc('');
                setSpecRequestPriority(0);
                await fetchActiveEventsManual();
                showToast('Запрос на мероприятие создан');
            } else {
                const error = await response.json().catch(() => ({} as unknown));
                showToast(getApiErrorMessage(error, 'Не удалось создать запрос'), 'error');
            }
        } catch (error) {
            console.error('Error creating spec request:', error);
            showToast('Ошибка при создании запроса', 'error');
        } finally {
            setSpecRequestLoading(false);
        }
    };

    const availableStreamerSlots = onlineStreamers.reduce((total, streamer) => {
        const assignments = streamer.assignments || [];
        const effectiveSlots = streamer.pr_slots_override ?? streamer.pr_slots;
        return total + Math.max(effectiveSlots - assignments.length, 0);
    }, 0);

    const availableEventSlots = activeEvents.reduce((total, event) => {
        if (event.event_kind === 'spec_request' && event.approval_status !== 'approved') {
            return total;
        }

        const participants = event.participants || [];
        const currentParticipants = event.current_participants ?? participants.length;
        const totalSlots = event.pr_slots ?? event.required_pr_count ?? 1;
        return total + Math.max(totalSlots - currentParticipants, 0);
    }, 0);

    const availableSlotsCount = availableStreamerSlots + availableEventSlots;

    const stats = [
        {
            label: 'Кол-во занятых PR',
            value: dashboardStats.assigned_pr_count,
            color: 'text-[#3b82f6]',
            icon: Users
        },
        {
            label: 'Стримеров в GTA',
            value: dashboardStats.unassigned_media_count,
            color: dashboardStats.unassigned_media_count > 0 ? 'text-[#9146ff]' : 'text-white',
            icon: Wifi
        },
        {
            label: 'Требуется ассистентов',
            value: availableSlotsCount,
            color: availableSlotsCount > 0 ? 'text-emerald-400' : 'text-white',
            icon: UserPlus
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
            title: 'Таблица PR Ассистентов',
            desc: 'Статистика работы сотрудников',
            path: '/assistants',
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
            title: 'Возвраты',
            desc: 'Очередь снятий и история перевыдач',
            path: '/returns',
            icon: Clock,
            color: 'from-cyan-500/20 to-cyan-600/5 hover:border-cyan-500/50',
            visible: canViewReturns,
        },
    ].filter((item) => item.visible !== false);

    const adminCategories = [
        {
            title: 'Админ-панель',
            desc: 'Управление доступом и настройками',
            path: '/admin',
            icon: ShieldAlert,
            color: 'from-red-500/20 to-red-600/5 hover:border-red-500/50 text-red-400',
            visible: canViewAdminSection,
        },
        {
            title: 'Bot Dashboard',
            desc: 'Состояние и логи бота',
            path: '/bot',
            icon: Bot,
            color: 'from-gray-500/20 to-gray-600/5 hover:border-gray-500/50',
            visible: canViewBotDashboard,
        },
    ].filter((item) => item.visible);

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
                    {!isGlobalClaimed && canRequestSpec && (
                        <button
                            onClick={(e) => { e.stopPropagation(); setIsSpecRequestOpen(true); }}
                            className="ml-4 flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 text-xs font-semibold hover:bg-amber-500/20 transition-colors text-amber-400 whitespace-nowrap"
                            title="Запросить спек"
                        >
                            <Plus className="w-3.5 h-3.5" />
                            Запросить спек
                        </button>
                    )}
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
                                        const isPending = event.event_kind === 'spec_request' && event.approval_status === 'pending';
                                        const participants = event.participants || [];
                                        const currentParticipants = event.current_participants || participants.length;
                                        const isUserParticipant = participants.some((p: EventParticipant) => String(p.pr_id) === String(user?.discord_id));
                                        return (
                                            <div key={`event-${event.id}`} className={`group flex items-center p-3 rounded-xl hover:bg-white/5 transition-all ${isPending ? 'opacity-60' : ''}`}>
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
                                                            {isPending && (
                                                                <span className="ml-2 inline-flex items-center gap-1 text-xs font-medium text-amber-400/70 bg-amber-500/10 px-2 py-0.5 rounded-full">
                                                                    <Clock className="w-3 h-3" />
                                                                    Ожидает
                                                                </span>
                                                            )}
                                                            {event.start_time && (
                                                                <span className="ml-2 text-purple-400 text-sm font-medium">
                                                                    [{formatMskToLocal(event.start_time)}]
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
                                                                        onClick={() => navigate(`/assistants/${participant.pr_id}`)}
                                                                        className={`font-bold cursor-pointer transition-colors ${participant.status === 'reserved' ? 'text-gray-400 hover:text-gray-300' : 'text-blue-400 hover:text-blue-300'}`}
                                                                        title={participant.status === 'reserved' ? 'Зарезервирован' : 'Активен'}
                                                                    >
                                                                        @{participant.nickname || participant.pr_id}
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            <div className="text-sm font-bold text-white/40 select-none">Ассистента нет</div>
                                                        )}
                                                    </div>
                                                    <div className="flex items-center gap-1.5 ml-2 shrink-0">
                                                        {isUserParticipant && canLeaveEvents ? (
                                                            <button
                                                                onClick={(e) => { e.stopPropagation(); void handleLeaveEvent(event.id); }}
                                                                className="px-3 py-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-xs font-semibold hover:bg-red-500/20 transition-colors text-red-400 whitespace-nowrap"
                                                            >
                                                                Открепиться
                                                            </button>
                                                        ) : !isUserParticipant && !isGlobalClaimed && event.event_kind !== 'spec_request' && canJoinEvents && (
                                                            <button
                                                                onClick={(e) => { e.stopPropagation(); void handleJoinEvent(event.id); }}
                                                                className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/80 whitespace-nowrap"
                                                            >
                                                                Закрепиться
                                                            </button>
                                                        )}
                                                        {canManageEvents && (
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
                                                        <div className="flex items-center gap-2 mt-1">
                                                            <a
                                                                href={`https://twitch.tv/${streamer.streamer_name}`}
                                                                target="_blank"
                                                                rel="noreferrer"
                                                                className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-[#9146ff]/10 text-[#9146ff] hover:bg-[#9146ff]/20 transition-colors text-xs font-semibold"
                                                                onClick={(e) => e.stopPropagation()}
                                                            >
                                                                <Twitch className="w-3.5 h-3.5" />
                                                                Перейти на канал
                                                            </a>
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
                                                                            navigate(`/assistants/${a.pr_id}`);
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
                                                        {isUserClaimed && canUnclaimSelf ? (
                                                            <button
                                                                onClick={(e) => { e.stopPropagation(); void handleUnclaimStreamer(streamer.streamer_id); }}
                                                                className="px-3 py-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-xs font-semibold hover:bg-red-500/20 transition-colors text-red-400 whitespace-nowrap"
                                                            >
                                                                Открепиться
                                                            </button>
                                                        ) : hasSlots && !isGlobalClaimed && canClaimMain && (
                                                            <>
                                                                <button
                                                                    onClick={(e) => { e.stopPropagation(); void handleClaimStreamer(streamer.streamer_id, false); }}
                                                                    className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/80 whitespace-nowrap"
                                                                >
                                                                    Закрепиться
                                                                </button>
                                                                {canClaimProbation && streamer.allow_juniors !== false && (
                                                                    <button
                                                                        onClick={(e) => { e.stopPropagation(); void handleClaimStreamer(streamer.streamer_id, true); }}
                                                                        className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/60 whitespace-nowrap"
                                                                    >
                                                                        Вторым
                                                                    </button>
                                                                )}
                                                            </>
                                                        )}
                                                        {canManageStreamers && (
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

            {adminCategories.length > 0 && (
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

            {/* Spec Request Modal */}
            {isSpecRequestOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]">
                    <div className="bg-[#1e1e1e] border border-white/10 rounded-2xl p-8 w-full max-w-md shadow-2xl">
                        <h3 className="text-xl font-bold text-white mb-6">Запросить спек</h3>
                        <div className="space-y-4">
                            <div>
                                <label className="block text-sm text-white/60 mb-1">Название</label>
                                <input
                                    type="text"
                                    value={specRequestName}
                                    onChange={(e) => setSpecRequestName(e.target.value)}
                                    className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-white placeholder-white/30 focus:outline-none focus:border-amber-500/50 transition-colors"
                                    placeholder="Название спека"
                                    maxLength={100}
                                />
                            </div>
                            <div>
                                <label className="block text-sm text-white/60 mb-1">Описание</label>
                                <textarea
                                    value={specRequestDesc}
                                    onChange={(e) => setSpecRequestDesc(e.target.value)}
                                    className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-white placeholder-white/30 focus:outline-none focus:border-amber-500/50 transition-colors resize-none"
                                    placeholder="Описание (необязательно)"
                                    rows={3}
                                    maxLength={1000}
                                />
                            </div>
                            <div>
                                <label className="block text-sm text-white/60 mb-1">Приоритет</label>
                                <div className="flex gap-2">
                                    {[0, 1, 2, 3].map((p) => (
                                        <button
                                            key={p}
                                            onClick={() => setSpecRequestPriority(p)}
                                            className={`flex-1 py-2 rounded-lg text-sm font-semibold transition-colors border ${specRequestPriority === p
                                                ? p === 0 ? 'bg-white/10 text-white border-white/30'
                                                    : p === 1 ? 'bg-green-500/20 text-green-400 border-green-500/30'
                                                        : p === 2 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
                                                            : 'bg-red-500/20 text-red-400 border-red-500/30'
                                                : 'bg-white/5 text-white/40 border-white/10 hover:bg-white/10'
                                                }`}
                                        >
                                            {p}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>
                        <div className="flex gap-3 mt-6">
                            <button
                                onClick={() => setIsSpecRequestOpen(false)}
                                className="flex-1 py-2.5 rounded-xl border border-white/10 text-white/60 font-semibold hover:bg-white/5 transition-colors"
                            >
                                Отмена
                            </button>
                            <button
                                onClick={() => void handleCreateSpecRequest()}
                                disabled={specRequestLoading || !specRequestName.trim()}
                                className="flex-1 py-2.5 rounded-xl bg-amber-500/20 border border-amber-500/30 text-amber-400 font-semibold hover:bg-amber-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                {specRequestLoading ? 'Отправка…' : 'Отправить'}
                            </button>
                        </div>
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

            <ConfirmDialog {...dialogProps} />

            {toast && (
                <NotificationToast
                    message={toast.message}
                    type={toast.type}
                    onClose={closeToast}
                />
            )}
        </div>
    );
}

export default MainHub;
