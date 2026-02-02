import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Twitch, User, Clock, Shield } from 'lucide-react';

export default function MediaProfile() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [streamer, setStreamer] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchStreamer = async () => {
            try {
                const response = await fetch(`/api/streamers/${id}`);
                if (!response.ok) {
                    throw new Error('Стример не найден');
                }
                const data = await response.json();
                setStreamer(data);
            } catch (err: any) {
                setError(err.message);
            } finally {
                setLoading(false);
            }
        };

        if (id) {
            fetchStreamer();
        }
    }, [id]);

    if (loading) {
        return (
            <div className="flex items-center justify-center min-h-[50vh] animate-pulse">
                <div className="text-xl font-bold text-white/40">Загрузка профиля...</div>
            </div>
        );
    }

    if (error || !streamer) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[50vh] gap-4">
                <div className="text-red-400 font-bold text-xl">{error || 'Стример не найден'}</div>
                <button
                    onClick={() => navigate(-1)}
                    className="flex items-center gap-2 px-6 py-2 rounded-xl bg-white/5 hover:bg-white/10 transition-all text-white"
                >
                    <ArrowLeft className="w-5 h-5" />
                    Назад
                </button>
            </div>
        );
    }

    return (
        <div className="max-w-4xl mx-auto space-y-8 animate-[fadeIn_0.5s_ease-in-out]">
            {/* Header / Banner area */}
            <div className="relative overflow-hidden rounded-3xl bg-[#242424]/80 backdrop-blur-md border border-white/5 p-8">
                <div className="relative z-10 flex flex-col md:flex-row gap-8 items-center md:items-start">

                    {/* Avatar / Image */}
                    <div className="w-32 h-32 rounded-full border-4 border-[#9146ff] shadow-[0_0_30px_rgba(145,70,255,0.3)] overflow-hidden shrink-0">
                        {streamer.profile_image_url || streamer.stream_thumbnail_url ? (
                            <img src={streamer.profile_image_url || streamer.stream_thumbnail_url} alt={streamer.streamer_name} className="w-full h-full object-cover" />
                        ) : (
                            <div className="w-full h-full bg-[#9146ff] flex items-center justify-center">
                                <Twitch className="w-16 h-16 text-white" />
                            </div>
                        )}
                    </div>

                    <div className="flex-1 text-center md:text-left space-y-4">
                        <div className="space-y-1">
                            <h1 className="text-4xl font-bold text-white flex items-center justify-center md:justify-start gap-3">
                                {streamer.streamer_name}
                                {streamer.is_online && (
                                    <span className="px-3 py-1 bg-red-500/20 text-red-400 text-xs rounded-full border border-red-500/20 animate-pulse">
                                        LIVE
                                    </span>
                                )}
                            </h1>
                            <div className="text-white/60 font-mono">ID: {streamer.streamer_id}</div>
                        </div>

                        <div className="flex flex-wrap justify-center md:justify-start gap-4">
                            <div className="px-4 py-2 rounded-xl bg-white/5 border border-white/5 flex items-center gap-2">
                                <Shield className="w-4 h-4 text-[#9146ff]" />
                                <span className="text-white/80">Приоритет: {streamer.priority}</span>
                            </div>
                            {streamer.game_name && (
                                <div className="px-4 py-2 rounded-xl bg-white/5 border border-white/5 flex items-center gap-2">
                                    <ActivityIcon className="w-4 h-4 text-green-400" />
                                    <span className="text-white/80">{streamer.game_name}</span>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="flex flex-col gap-3 shrink-0">
                        <a
                            href={`https://twitch.tv/${streamer.streamer_name}`}
                            target="_blank"
                            rel="noreferrer"
                            className="px-6 py-3 rounded-xl bg-[#9146ff] hover:bg-[#7c2cf5] text-white font-bold transition-all shadow-lg shadow-[#9146ff]/20 flex items-center justify-center gap-2"
                        >
                            <Twitch className="w-5 h-5" />
                            Перейти на Twitch
                        </a>
                        <button
                            onClick={() => navigate(-1)}
                            className="px-6 py-3 rounded-xl bg-white/5 hover:bg-white/10 text-white font-medium transition-all flex items-center justify-center gap-2"
                        >
                            <ArrowLeft className="w-5 h-5" />
                            Назад
                        </button>
                    </div>
                </div>
            </div>

            {/* Details Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="p-6 rounded-2xl bg-[#242424]/50 border border-white/5 space-y-4">
                    <h3 className="text-xl font-bold flex items-center gap-2">
                        <User className="w-5 h-5 text-blue-400" />
                        Закрепленный PR
                    </h3>
                    <div className="p-4 rounded-xl bg-black/20 border border-white/5">
                        {streamer.assigned_pr_id ? (
                            <div className="flex items-center justify-between">
                                <span className="text-white">ID сотрудника: {streamer.assigned_pr_id}</span>
                                <span className="text-sm text-green-400">Активен</span>
                            </div>
                        ) : (
                            <div className="text-white/40 flex flex-col items-center py-4 gap-2">
                                <span>Нет закрепленного сотрудника</span>
                                <button className="px-4 py-1.5 rounded-lg bg-blue-500/20 text-blue-400 text-sm hover:bg-blue-500/30 transition-colors">
                                    Взять в работу
                                </button>
                            </div>
                        )}
                    </div>
                </div>

                <div className="p-6 rounded-2xl bg-[#242424]/50 border border-white/5 space-y-4">
                    <h3 className="text-xl font-bold flex items-center gap-2">
                        <Clock className="w-5 h-5 text-orange-400" />
                        История стримов
                    </h3>
                    <div className="text-white/40 text-center py-8">
                        История пока недоступна
                    </div>
                </div>
            </div>
        </div>
    );
}

function ActivityIcon(props: any) {
    return (
        <svg
            {...props}
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
        >
            <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
        </svg>
    )
}
