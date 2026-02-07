
import { useNavigate, useOutletContext } from 'react-router-dom';
import { MapPin, ExternalLink, Users, Settings } from 'lucide-react';

interface StreamerCardProps {
    streamer: any;
    onSettingsClick?: (streamer: any) => void;
}

const StreamerCard = ({ streamer, onSettingsClick }: StreamerCardProps) => {
    const navigate = useNavigate();
    const { user } = useOutletContext<any>() || {};
    const userRole = user?.role;

    return (
        <div className="p-3 rounded-xl flex items-center group hover:bg-white/5 transition-all">
            {/* Left Section: Priority + Profile Button + Name & Link */}
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
                {streamer.assigned_pr_id ? (
                    <div className="w-full flex justify-center">
                        <div className="flex flex-col items-center">
                            <span className="text-sm font-bold text-white/90">
                                {streamer.assigned_pr_name || 'Сотрудник'}
                            </span>
                            <span className="text-xs text-white/40">
                                ({streamer.assigned_pr_id})
                            </span>
                        </div>
                    </div>
                ) : (
                    <div className="w-full relative flex items-center justify-center">
                        <div className="text-sm font-bold text-white/40 select-none">
                            Ассистента нет
                        </div>
                        <button className="absolute right-0 top-1/2 -translate-y-1/2 px-3 py-1.5 rounded-lg border border-white/10 text-xs font-semibold hover:bg-white/5 transition-colors text-white/80 whitespace-nowrap">
                            Закрепиться
                        </button>
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
    );
}

export default StreamerCard;
