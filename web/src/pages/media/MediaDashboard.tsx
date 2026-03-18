import React from 'react';
import { ChevronDown } from 'lucide-react';
import StreamerCard from './components/StreamerCard';
import StreamerSettingsModal from './components/StreamerSettingsModal';
import type { Streamer } from '../../types/domain';
import { unwrapApiData } from '../../types/api';
import { apiFetch } from '../../api/client';

export function MediaDashboard() {
    const [streamers, setStreamers] = React.useState<Streamer[]>([]);
    const [loading, setLoading] = React.useState(true);
    const [selectedStreamer, setSelectedStreamer] = React.useState<Streamer | null>(null);
    const [isMediaOpen, setIsMediaOpen] = React.useState(true);

    React.useEffect(() => {
        fetchStreamers();
        const interval = setInterval(fetchStreamers, 10000);
        return () => clearInterval(interval);
    }, []);

    const fetchStreamers = async () => {
        try {
            const response = await apiFetch('/api/streamers');
            if (response.ok) {
                const json = await response.json() as unknown;
                const data = unwrapApiData<{ streamers: Streamer[] } | Streamer[]>(json);
                const normalized = Array.isArray(data) ? data : data.streamers;
                setStreamers(Array.isArray(normalized) ? normalized : []);
            }
        } catch (error) {
            console.error('Failed to fetch streamers:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleUpdateStreamer = async (updates: {
        priority?: number;
        pr_slots?: number;
        is_pinned?: boolean;
        allow_juniors?: boolean;
        current_stream_priority_override?: number;
        current_stream_pr_slots_override?: number;
    }) => {
        if (!selectedStreamer) return;
        try {
            const response = await apiFetch(`/api/streamers/${selectedStreamer.streamer_id}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(updates)
            });
            if (response.ok) {
                await fetchStreamers();
            }
        } catch (error) {
            console.error('Failed to update streamer:', error);
        }
    };

    // Split streamers into two columns for the dashboard
    const midPoint = Math.ceil(streamers.length / 2);
    const leftColumn = streamers.slice(0, midPoint);
    const rightColumn = streamers.slice(midPoint);

    if (loading) return null;

    return (
        <div className="select-none">
            <h2
                className="text-2xl font-bold mb-6 flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity"
                onClick={() => setIsMediaOpen(!isMediaOpen)}
            >
                <span className="w-1 h-8 bg-purple-500 rounded-full inline-block"></span>
                Медиа
                <div className={`ml-auto p-2 rounded-full bg-white/5 transition-transform duration-300 ${isMediaOpen ? 'rotate-180' : ''}`}>
                    <ChevronDown className="w-5 h-5 text-white/60" />
                </div>
            </h2>

            <div className={`transition-all duration-300 ${isMediaOpen ? 'opacity-100' : 'opacity-0 h-0 overflow-hidden'}`}>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* Left Column Table */}
                    <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden p-2">
                        <div className="flex flex-col gap-1">
                            {leftColumn.length > 0 ? (
                                leftColumn.map(s => <StreamerCard key={s.streamer_id} streamer={s} onSettingsClick={setSelectedStreamer} />)
                            ) : (
                                <div className="text-white/40 text-center py-8">Нет данных</div>
                            )}
                        </div>
                    </div>

                    {/* Right Column Table */}
                    <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden p-2">
                        <div className="flex flex-col gap-1">
                            {rightColumn.length > 0 ? (
                                rightColumn.map(s => <StreamerCard key={s.streamer_id} streamer={s} onSettingsClick={setSelectedStreamer} />)
                            ) : (
                                <div className="text-white/40 text-center py-8">Нет данных</div>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            <StreamerSettingsModal
                streamer={selectedStreamer}
                isOpen={!!selectedStreamer}
                onClose={() => setSelectedStreamer(null)}
                onSave={handleUpdateStreamer}
                mode="global"
            />
        </div>
    );
}

export default MediaDashboard;
