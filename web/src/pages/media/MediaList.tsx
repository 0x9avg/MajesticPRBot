import React from 'react';
import { Radio, Activity } from 'lucide-react';
import StreamerCard from './components/StreamerCard';
import StreamerSettingsModal from './components/StreamerSettingsModal';

export function MediaList() {
    const [activeTab, setActiveTab] = React.useState<'activities' | 'all' | 'stats'>('activities');
    const [streamers, setStreamers] = React.useState<any[]>([]);
    const [loading, setLoading] = React.useState(true);
    const [selectedStreamer, setSelectedStreamer] = React.useState<any>(null);

    React.useEffect(() => {
        fetchStreamers();
        const interval = setInterval(fetchStreamers, 10000);
        return () => clearInterval(interval);
    }, []);

    const fetchStreamers = async () => {
        try {
            const response = await fetch('/api/streamers');
            if (response.ok) {
                const json = await response.json();
                const data = (json.data && json.data.streamers) || json.streamers || [];
                setStreamers(data);
            }
        } catch (error) {
            console.error('Failed to fetch streamers:', error);
        } finally {
            setLoading(false);
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
                fetchStreamers();
            }
        } catch (error) {
            console.error('Failed to update streamer:', error);
        }
    };

    const tabs = [
        { id: 'activities' as const, label: 'Активности' },
        { id: 'all' as const, label: 'Все медиа' },
        { id: 'stats' as const, label: 'Статистика' }
    ];

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
                                {streamers.length > 0 ? (
                                    streamers.map(s => <StreamerCard key={s.streamer_id} streamer={s} onSettingsClick={setSelectedStreamer} />)
                                ) : (
                                    <div className="text-white/40 text-center py-8">Нет данных</div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'all' && (
                <div className="animate-[fadeIn_0.3s_ease-in-out]">
                    <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-8">
                        <div className="text-center text-white/60">
                            <Radio className="w-16 h-16 mx-auto mb-4 text-white/40" />
                            <h3 className="text-xl font-bold text-white mb-2">Все медиа</h3>
                            <p className="text-sm">Полный список медиа-ресурсов появится здесь</p>
                        </div>
                    </div>
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
        </div>
    );
}

export default MediaList;
