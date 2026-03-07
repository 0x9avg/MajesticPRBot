
import React from 'react';

import { useNavigate, useOutletContext } from 'react-router-dom';
import { ExternalLink, Users, Settings, Trash2 } from 'lucide-react';
import type { OutletUserContext } from '../../../types/auth';
import type { Streamer } from '../../../types/domain';
import { hasAny } from '../../../rbac/guards';

void React;

interface StreamerCardProps {
    streamer: Streamer;
    onSettingsClick?: (streamer: Streamer) => void;
    onDelete?: (streamer: Streamer) => void;
}

const StreamerCard = ({ streamer, onSettingsClick, onDelete }: StreamerCardProps) => {
    const navigate = useNavigate();
    const { user } = useOutletContext<OutletUserContext>();
    const canManageStreamer = hasAny(user, ['streamers.update', 'streamers.delete']);

    return (
        <>
            <div className="p-3 rounded-xl flex items-center group hover:bg-white/5 transition-all">
                <div className="flex items-center gap-4 flex-1 min-w-0 mr-2">
                    {/* Priority Box */}
                    <div className={`w-8 h-8 rounded-lg border-2 flex items-center justify-center font-bold select-none shrink-0 relative ${streamer.priority === 1 ? 'bg-green-500/20 text-green-400 border-green-500/30' :
                        streamer.priority === 2 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' :
                            streamer.priority === 3 ? 'bg-red-500/20 text-red-400 border-red-500/30' :
                                'bg-white/5 text-white/50 border-white/20'
                        }`}>
                        {streamer.priority}
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

                {/* Right Section: Settings (Border Left) */}
                {canManageStreamer && (
                    <div className="flex justify-center pl-4 border-l border-white/10">
                        <button
                            onClick={() => onSettingsClick && onSettingsClick(streamer)}
                            className="p-2 hover:bg-white/5 rounded-lg text-white/40 hover:text-white transition-colors"
                        >
                            <Settings className="w-5 h-5" />
                        </button>
                        {onDelete && (
                            <button
                                onClick={() => {
                                    onDelete(streamer);
                                }}
                                className="p-2 hover:bg-red-500/10 rounded-lg text-white/40 hover:text-red-400 transition-colors"
                            >
                                <Trash2 className="w-5 h-5" />
                            </button>
                        )}
                    </div>
                )}
            </div>
        </>
    );
}

export default StreamerCard;
