import React from 'react';
import { useOutletContext } from 'react-router-dom';
import { Activity } from 'lucide-react';
import ConfirmDialog from '../../components/feedback/ConfirmDialog';
import NotificationToast from '../../components/feedback/NotificationToast';
import { useConfirmDialog, usePopupToast } from '../../components/feedback/hooks';
import StreamerCard from './components/StreamerCard';
import StreamerSettingsModal from './components/StreamerSettingsModal';
import type { OutletUserContext } from '../../types/auth';
import type { Streamer } from '../../types/domain';
import { unwrapApiData } from '../../types/api';
import { apiFetch } from '../../api/client';

export function MediaList() {
    useOutletContext<OutletUserContext>();
    const { toast, showToast, closeToast } = usePopupToast(3000);
    const { confirm, dialogProps } = useConfirmDialog();
    const [activeTab, setActiveTab] = React.useState<'all' | 'stats'>('all');
    const [allStreamers, setAllStreamers] = React.useState<Streamer[]>([]);
    const [loading, setLoading] = React.useState(true);
    const [selectedStreamer, setSelectedStreamer] = React.useState<Streamer | null>(null);

    const fetchAllStreamers = React.useCallback(async () => {
        try {
            const response = await apiFetch('/api/streamers');
            if (response.ok) {
                const json = await response.json() as unknown;
                const data = unwrapApiData<{ streamers: Streamer[] } | Streamer[]>(json);
                const normalized = Array.isArray(data) ? data : data.streamers;
                setAllStreamers(Array.isArray(normalized) ? normalized : []);
            }
        } catch (error) {
            console.error('Failed to fetch all streamers:', error);
        }
    }, []);

    React.useEffect(() => {
        const fetchData = async () => {
            await fetchAllStreamers();
            setLoading(false);
        };
        void fetchData();
        const interval = setInterval(() => {
            void fetchAllStreamers();
        }, 10000);
        return () => clearInterval(interval);
    }, [fetchAllStreamers]);

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
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(updates)
            });
            if (response.ok) {
                await fetchAllStreamers();
                showToast('Настройки стримера сохранены');
            } else {
                showToast('Не удалось сохранить настройки стримера', 'error');
            }
        } catch (error) {
            console.error('Failed to update streamer:', error);
            showToast('Не удалось сохранить настройки стримера', 'error');
        }
    };

    const handleDeleteStreamer = async (streamer: Streamer) => {
        const confirmed = await confirm({
            title: 'Удалить стримера?',
            message: <>Стример <span className="text-white font-semibold">{streamer.streamer_name}</span> будет удален из общего списка.</>,
            confirmLabel: 'Удалить',
            tone: 'danger',
        });
        if (!confirmed) return;

        try {
            const response = await apiFetch(`/api/streamers/${streamer.streamer_id}`, {
                method: 'DELETE',
            });
            if (response.ok) {
                await fetchAllStreamers();
                showToast(`Стример ${streamer.streamer_name} удален`);
            } else {
                console.error('Failed to delete streamer');
                showToast(`Не удалось удалить стримера ${streamer.streamer_name}`, 'error');
            }
        } catch (error) {
            console.error('Failed to delete streamer:', error);
            showToast(`Не удалось удалить стримера ${streamer.streamer_name}`, 'error');
        }
    };

    const tabs = [
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
            {activeTab === 'all' && (
                <div className="animate-[fadeIn_0.3s_ease-in-out]">
                    {loading ? (
                        <div className="text-white/60 text-center py-12">Загрузка...</div>
                    ) : (
                        <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden p-2">
                            <div className="flex flex-col gap-1">
                                {allStreamers.length > 0 ? (
                                    allStreamers.map(s => <StreamerCard key={s.streamer_id} streamer={s} onSettingsClick={setSelectedStreamer} onDelete={handleDeleteStreamer} />)
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
                mode="global"
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
export default MediaList;
