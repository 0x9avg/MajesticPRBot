import React from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { MapPin, CalendarDays, Settings, Activity } from 'lucide-react';
import StreamerCard from './components/StreamerCard';
import StreamerSettingsModal from './components/StreamerSettingsModal';
import EventSettingsModal from './components/EventSettingsModal';

export function MediaList() {
    const { user } = useOutletContext<any>() || {};
    const [activeTab, setActiveTab] = React.useState<'activities' | 'all' | 'stats'>('activities');
    const [onlineStreamers, setOnlineStreamers] = React.useState<any[]>([]);
    const [allStreamers, setAllStreamers] = React.useState<any[]>([]);
    const [events, setEvents] = React.useState<any[]>([]);
    const [loading, setLoading] = React.useState(true);
    const [selectedStreamer, setSelectedStreamer] = React.useState<any>(null);
    const [selectedEvent, setSelectedEvent] = React.useState<any>(null);
    const navigate = useNavigate();

    React.useEffect(() => {
        fetchAllData();
        const interval = setInterval(fetchAllData, 10000);
        return () => clearInterval(interval);
    }, []);

    const fetchAllData = async () => {
        await Promise.all([
            fetchOnlineStreamers(),
            fetchAllStreamers(),
            fetchActiveEvents()
        ]);
        setLoading(false);
    };

    const fetchOnlineStreamers = async () => {
        try {
            const response = await fetch('/api/streamers?online_only=true');
            if (response.ok) {
                const json = await response.json();
                const data = (json.data && json.data.streamers) || json.streamers || [];
                setOnlineStreamers(data);
            }
        } catch (error) {
            console.error('Failed to fetch online streamers:', error);
        }
    };

    const fetchAllStreamers = async () => {
        try {
            const response = await fetch('/api/streamers');
            if (response.ok) {
                const json = await response.json();
                const data = (json.data && json.data.streamers) || json.streamers || [];
                setAllStreamers(data);
            }
        } catch (error) {
            console.error('Failed to fetch all streamers:', error);
        }
    };

    const fetchActiveEvents = async () => {
        try {
            const response = await fetch('/api/events/active');
            if (response.ok) {
                const json = await response.json();
                const data = json.data || [];
                setEvents(data);
            }
        } catch (error) {
            console.error('Failed to fetch active events:', error);
        }
    };

    const handleUpdateStreamer = async (updates: any) => {
        if (!selectedStreamer) return;
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`/api/streamers/${selectedStreamer.streamer_id}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify(updates)
            });
            if (response.ok) {
                await fetchAllData();
            }
        } catch (error) {
            console.error('Failed to update streamer:', error);
        }
    };

    const handleUpdateEvent = async (updates: any) => {
        if (!selectedEvent) return;
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`/api/events/${selectedEvent.id}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify(updates)
            });
            if (response.ok) {
                await fetchAllData();
            }
        } catch (error) {
            console.error('Failed to update event:', error);
        }
    };

    const handleJoinEvent = async (event: any) => {
        if (!user) return;
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`/api/events/${event.id}/join`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({ user_id: user.discord_id })
            });

            if (response.ok) {
                await fetchAllData();
            } else {
                console.error('Failed to join event');
            }
        } catch (error) {
            console.error('Error joining event:', error);
        }
    };

    const handleUnjoinEvent = async (event: any) => {
        if (!user) return;
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`/api/events/${event.id}/leave`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({ user_id: user.discord_id })
            });

            if (response.ok) {
                await fetchAllData();
            } else {
                console.error('Failed to leave event');
            }
        } catch (error) {
            console.error('Error leaving event:', error);
        }
    };

    const tabs = [
        { id: 'activities' as const, label: 'Активности' },
        { id: 'all' as const, label: 'Все медиа' },
        { id: 'stats' as const, label: 'Статистика' }
    ];

    const userRole = user?.role;

    return (
        <div className="space-y-6">
            <h2 className="text-3xl font-bold flex items-center gap-2">
                <span className="w-1 h-8 bg-purple-500 rounded-full inline-block"></span>
                Медиа
            </h2>

            {/* Tabs */}
            <div className="flex gap-2 border-b border-white/10 pb-2">
                {tabs.map(tab => (
                    <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        className={`px-6 py-3 rounded-t-lg font-semibold transition-all ${activeTab === tab.id
                            ? 'bg-white/10 text-white border-b-2 border-purple-500'
                            : 'text-white/60 hover:text-white hover:bg-white/5'
                            }`}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {/* Tab Content */}
            {activeTab === 'activities' && (
                <div className="animate-[fadeIn_0.3s_ease-in-out]">
                    {loading ? (
                        <div className="text-white/60 text-center py-12">Загрузка...</div>
                    ) : (
                        <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden p-2">
                            <div className="flex flex-col gap-1">
                                {(() => {
                                    // Combine events and streamers into one array
                                    const allItems = [
                                        ...events.map((event: any) => ({ ...event, type: 'event' })),
                                        ...onlineStreamers.map((streamer: any) => ({ ...streamer, type: 'streamer' }))
                                    ];

                                    // Sort by is_pinned DESC, then priority DESC
                                    const sortedItems = allItems.sort((a, b) => {
                                        // First by pinned status
                                        const aPinned = a.is_pinned ? 1 : 0;
                                        const bPinned = b.is_pinned ? 1 : 0;
                                        if (aPinned !== bPinned) return bPinned - aPinned;

                                        // Then by priority
                                        const aPriority = a.priority || 0;
                                        const bPriority = b.priority || 0;
                                        return bPriority - aPriority;
                                    });

                                    if (sortedItems.length === 0) {
                                        return <div className="text-white/40 text-center py-8">Нет активностей</div>;
                                    }

                                    return sortedItems.map((item: any) => {
                                        if (item.type === 'event') {
                                            const event = item;
                                            const isAssigned = event.participants?.some((p: any) => String(p.pr_id) === String(user?.discord_id));
                                            return (
                                                <div key={`event-${event.id}`} className="group flex items-center p-3 rounded-xl hover:bg-white/5 transition-all">
                                                    {/* Left Section: Priority + Icon + Name */}
                                                    <div className="flex items-center gap-4 flex-1 min-w-0 mr-2">
                                                        {/* Priority Box */}
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

                                                        {/* Event Icon */}
                                                        <div className="w-9 h-9 rounded-lg bg-purple-500/20 flex items-center justify-center text-purple-400 shrink-0">
                                                            <CalendarDays className="w-5 h-5" />
                                                        </div>

                                                        {/* Info */}
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

                                                    {/* Middle Section: Status & Action Merged */}
                                                    <div className="flex-[2] flex items-center px-4 border-l border-white/10 relative">
                                                        {event.current_participants > 0 ? (
                                                            <div className="w-full relative flex items-center justify-center">
                                                                <div className="flex items-center gap-2 text-white/60">
                                                                    <div className="flex flex-wrap gap-2 justify-center">
                                                                        {event.participants && event.participants.map((p: any) => (
                                                                            <span
                                                                                key={p.pr_id}
                                                                                onClick={(e) => {
                                                                                    e.stopPropagation();
                                                                                    navigate(`/profile/${p.pr_id}`);
                                                                                }}
                                                                                className="font-bold text-white hover:text-blue-400 cursor-pointer transition-colors"
                                                                            >
                                                                                @{p.nickname}
                                                                            </span>
                                                                        ))}
                                                                        {(!event.participants || event.participants.length === 0) && (
                                                                            <span className="font-bold text-white">{event.current_participants}</span>
                                                                        )}
                                                                    </div>
                                                                </div>
                                                                {(isAssigned || (event.current_participants < (event.pr_slots || event.required_pr_count))) && (
                                                                    <div className="absolute right-0 top-1/2 -translate-y-1/2 flex flex-col gap-1.5 items-end">
                                                                        {isAssigned ? (
                                                                            <button
                                                                                onClick={() => handleUnjoinEvent(event)}
                                                                                className="px-3 py-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-xs font-semibold hover:bg-red-500/20 transition-colors text-red-400 whitespace-nowrap w-full"
                                                                            >
                                                                                Открепиться
                                                                            </button>
                                                                        ) : (
                                                                            <>
                                                                                <button
                                                                                    onClick={() => handleJoinEvent(event)}
                                                                                    className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/80 whitespace-nowrap w-full"
                                                                                >
                                                                                    Закрепиться
                                                                                </button>
                                                                                {userRole === 'junior_employee' && (
                                                                                    <button
                                                                                        onClick={() => handleJoinEvent(event)}
                                                                                        className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/60 whitespace-nowrap w-full"
                                                                                    >
                                                                                        Вторым
                                                                                    </button>
                                                                                )}
                                                                            </>
                                                                        )}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        ) : (
                                                            <div className="w-full relative flex items-center justify-center">
                                                                <div className="text-sm font-bold text-white/40 select-none">
                                                                    Ассистента нет
                                                                </div>
                                                                <div className="absolute right-0 top-1/2 -translate-y-1/2 flex flex-col gap-1.5 items-end">
                                                                    <button
                                                                        onClick={() => handleJoinEvent(event)}
                                                                        className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/80 whitespace-nowrap w-full"
                                                                    >
                                                                        Закрепиться
                                                                    </button>
                                                                    {userRole === 'junior_employee' && (
                                                                        <button
                                                                            onClick={() => handleJoinEvent(event)}
                                                                            className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/60 whitespace-nowrap w-full"
                                                                        >
                                                                            Вторым
                                                                        </button>
                                                                    )}
                                                                </div>
                                                            </div>
                                                        )}
                                                    </div>

                                                    {/* Right Section: Settings */}
                                                    {(userRole === 'manager' || userRole === 'developer') && (
                                                        <div className="flex justify-center pl-4 border-l border-white/10">
                                                            <button
                                                                onClick={() => setSelectedEvent(event)}
                                                                className="p-2 hover:bg-white/5 rounded-lg text-white/40 hover:text-white transition-colors"
                                                            >
                                                                <Settings className="w-5 h-5" />
                                                            </button>
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        } else {
                                            const streamer = item;
                                            return <StreamerCard key={streamer.streamer_id} streamer={streamer} onSettingsClick={setSelectedStreamer} />;
                                        }
                                    });
                                })()}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'all' && (
                <div className="animate-[fadeIn_0.3s_ease-in-out]">
                    {loading ? (
                        <div className="text-white/60 text-center py-12">Загрузка...</div>
                    ) : (
                        <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden p-2">
                            <div className="flex flex-col gap-1">
                                {allStreamers.length > 0 ? (
                                    allStreamers.map(s => <StreamerCard key={s.streamer_id} streamer={s} onSettingsClick={setSelectedStreamer} />)
                                ) : (
                                    <div className="text-white/40 text-center py-8">Нет данных</div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'stats' && (
                <div className="animate-[fadeIn_0.3s_ease-in-out]">
                    <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-8">
                        <div className="text-center text-white/60">
                            <Activity className="w-16 h-16 mx-auto mb-4 text-white/40" />
                            <h3 className="text-xl font-bold text-white mb-2">Статистика медиа</h3>
                            <p className="text-sm">Статистика и аналитика появятся здесь</p>
                        </div>
                    </div>
                </div>
            )}

            <StreamerSettingsModal
                streamer={selectedStreamer}
                isOpen={!!selectedStreamer}
                onClose={() => setSelectedStreamer(null)}
                onSave={handleUpdateStreamer}
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
export default MediaList;
