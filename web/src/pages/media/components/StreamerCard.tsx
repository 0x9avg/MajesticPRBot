
import { useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { MapPin, ExternalLink, Users, Settings } from 'lucide-react';
import NotificationToast from '../../action-logs/components/NotificationToast';

interface StreamerCardProps {
    streamer: any;
    onSettingsClick?: (streamer: any) => void;
}

const StreamerCard = ({ streamer, onSettingsClick }: StreamerCardProps) => {
    const navigate = useNavigate();
    const { user } = useOutletContext<any>() || {};
    const userRole = user?.role;
    const [notification, setNotification] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

    const showNotification = (message: string, type: 'success' | 'error' = 'success') => {
        setNotification({ message, type });
        setTimeout(() => setNotification(null), 3000);
    };

    const handleClaimStreamer = async (isProbation: boolean) => {
        if (!user?.discord_id) return;

        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch('/api/spec/claim', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    streamer_id: streamer.streamer_id,
                    pr_id: user.discord_id,
                    is_probation: isProbation
                })
            });

            if (response.ok) {
                // Reload page to refresh data
                window.location.reload();
            } else {
                const error = await response.json();
                showNotification(error.detail || error.message || 'Не удалось закрепиться', 'error');
            }
        } catch (error) {
            console.error('Error claiming streamer:', error);
            showNotification('Ошибка при закреплении', 'error');
        }
    };

    const handleUnclaimStreamer = async (e: React.MouseEvent) => {
        e.stopPropagation();
        if (!user?.discord_id) return;

        // TODO: на будущее сделать подтверждение.

        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch('/api/spec/unclaim', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    streamer_id: streamer.streamer_id,
                    pr_id: user.discord_id,
                    reason: 'manual_unclaim'
                })
            });

            if (response.ok) {
                window.location.reload();
            } else {
                const error = await response.json();
                showNotification(error.detail || error.message || 'Не удалось открепиться', 'error');
            }
        } catch (error) {
            console.error('Error unclaiming streamer:', error);
            showNotification('Ошибка при откреплении', 'error');
        }
    };

    return (
        <>
            {notification && (
                <NotificationToast
                    message={notification.message}
                    type={notification.type}
                    onClose={() => setNotification(null)}
                />
            )}
            <div className="p-3 rounded-xl flex items-center group hover:bg-white/5 transition-all">
                <div className="flex items-center gap-4 flex-1 min-w-0 mr-2">
                    {/* Priority Box */}
                    <div className={`w-8 h-8 rounded-lg border-2 flex items-center justify-center font-bold select-none shrink-0 relative ${streamer.priority === 1 ? 'bg-green-500/20 text-green-400 border-green-500/30' :
                        streamer.priority === 2 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' :
                            streamer.priority === 3 ? 'bg-red-500/20 text-red-400 border-red-500/30' :
                                'bg-white/5 text-white/50 border-white/20'
                        }`}>
                        {streamer.priority}
                        {streamer.is_pinned && (
                            <div className="absolute -top-2 -right-2 bg-blue-500 text-white p-0.5 rounded-full shadow-lg border border-[#1e1e1e]">
                                <MapPin className="w-3 h-3" />
                            </div>
                        )}
                    </div>

                    {/* Profile Button -> Media Profile */}
                    <button
                        onClick={() => navigate(`/media/${streamer.streamer_id}`)}
                        className="p-2 hover:bg-white/10 rounded-lg text-white/60 hover:text-white transition-colors shrink-0"
                        title="Открыть профиль медиа"
                    >
                        <Users className="w-5 h-5" />
                    </button>

                    {/* Name -> Twitch */}
                    <a
                        href={`https://twitch.tv/${streamer.streamer_name}`}
                        target="_blank"
                        rel="noreferrer"
                        className="flex items-center gap-2 min-w-0 group/link p-1 -ml-1 hover:bg-white/5 rounded-lg transition-all"
                        title="Открыть Twitch"
                    >
                        <span className="font-bold text-lg text-white truncate group-hover/link:text-[#3b82f6] transition-colors">
                            {streamer.streamer_name}
                        </span>
                        <ExternalLink className="w-4 h-4 text-white/40 group-hover/link:text-white transition-colors shrink-0" />
                    </a>
                </div>

                {/* Middle Section: Status & Action Merged */}
                <div className="flex-[2] flex items-center px-4 border-l border-white/10 relative">
                    {streamer.assignments && streamer.assignments.length > 0 ? (
                        <div className="w-full relative flex items-center justify-center">
                            <div className="flex items-center gap-2 text-white/60">
                                <div className="flex flex-wrap gap-2 justify-center">
                                    {streamer.assignments.map((assignment: any) => (
                                        <span
                                            key={assignment.pr_id}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                navigate(`/profile/${assignment.pr_id}`);
                                            }}
                                            className="font-bold text-white hover:text-blue-400 cursor-pointer transition-colors"
                                        >
                                            @{assignment.nickname || assignment.pr_id}
                                        </span>
                                    ))}
                                </div>
                            </div>

                            {/* Actions */}
                            <div className="absolute right-0 top-1/2 -translate-y-1/2 flex flex-col gap-1.5 items-end">
                                {streamer.assignments.some((a: any) => String(a.pr_id) === String(user?.discord_id)) ? (
                                    <button
                                        onClick={handleUnclaimStreamer}
                                        className="px-3 py-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-xs font-semibold hover:bg-red-500/20 transition-colors text-red-400 whitespace-nowrap w-full"
                                    >
                                        Открепиться
                                    </button>
                                ) : (streamer.assignments.length < streamer.pr_slots) && (
                                    <>
                                        <button onClick={() => handleClaimStreamer(false)} className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/80 whitespace-nowrap w-full">
                                            Закрепиться
                                        </button>
                                        {userRole === 'junior_employee' && (
                                            <button onClick={() => handleClaimStreamer(true)} className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/60 whitespace-nowrap w-full">
                                                Вторым
                                            </button>
                                        )}
                                    </>
                                )}
                            </div>
                        </div>
                    ) : (
                        <div className="w-full relative flex items-center justify-center">
                            <div className="text-sm font-bold text-white/40 select-none">
                                Ассистента нет
                            </div>
                            <div className="absolute right-0 top-1/2 -translate-y-1/2 flex flex-col gap-1.5 items-end">
                                <button onClick={() => handleClaimStreamer(false)} className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/80 whitespace-nowrap w-full">
                                    Закрепиться
                                </button>
                                {userRole === 'junior_employee' && (
                                    <button onClick={() => handleClaimStreamer(true)} className="px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/60 whitespace-nowrap w-full">
                                        Вторым
                                    </button>
                                )}
                            </div>
                        </div>
                    )}
                </div>

                {/* Right Section: Settings (Border Left) */}
                {(userRole === 'manager' || userRole === 'developer') && (
                    <div className="flex justify-center pl-4 border-l border-white/10">
                        <button
                            onClick={() => onSettingsClick && onSettingsClick(streamer)}
                            className="p-2 hover:bg-white/5 rounded-lg text-white/40 hover:text-white transition-colors"
                        >
                            <Settings className="w-5 h-5" />
                        </button>
                    </div>
                )}
            </div>
        </>
    );
}

export default StreamerCard;
