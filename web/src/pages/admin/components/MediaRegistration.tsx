import React from 'react';
import { Radio, Share2 } from 'lucide-react';
import { CustomSelect } from '../../../components/CustomInputs';

const MediaRegistration = () => {
    const [platform, setPlatform] = React.useState('twitch');
    const [priority, setPriority] = React.useState(0);

    const getPlatformPrefix = (p: string) => {
        switch (p) {
            case 'twitch': return 'https://twitch.tv/';
            case 'youtube': return 'https://youtube.com/@';
            case 'tiktok': return 'https://tiktok.com/@';
            case 'kick': return 'https://kick.com/';
            case 'telegram': return 'https://t.me/';
            case 'discord': return 'https://discord.gg/';
            default: return 'https://';
        }
    };

    return (
        <div className="max-w-2xl mx-auto space-y-8 animate-[fadeIn_0.3s_ease-in-out]">
            <div className="flex items-center gap-4 border-b border-white/10 pb-6">
                <div className="w-12 h-12 rounded-xl bg-orange-500/20 text-orange-400 flex items-center justify-center border border-orange-500/30">
                    <Radio className="w-6 h-6" />
                </div>
                <div>
                    <h2 className="text-2xl font-bold text-white">Регистрация медиа</h2>
                    <p className="text-white/60">Добавление нового стримера или партнера</p>
                </div>
            </div>

            <div className="space-y-6">
                <div>
                    <label className="text-sm font-medium text-white/60 mb-2 block">Название канала / Никнейм</label>
                    <input type="text" className="w-full bg-black/20 border border-white/10 rounded-xl p-3 text-white focus:outline-none focus:border-orange-500/50 transition-colors" placeholder="Channel Name" />
                </div>

                <div className="grid grid-cols-2 gap-6">
                    <div>
                        <label className="text-sm font-medium text-white/60 mb-2 block">Платформа</label>
                        <CustomSelect
                            options={[
                                { value: 'twitch', label: 'Twitch' },
                                { value: 'youtube', label: 'YouTube' },
                                { value: 'tiktok', label: 'TikTok' },
                                { value: 'kick', label: 'Kick' },
                                { value: 'telegram', label: 'Telegram' },
                                { value: 'discord', label: 'Discord' }
                            ]}
                            value={platform}
                            onChange={(val) => setPlatform(val as string)}
                            placeholder="Платформа"
                            icon={<Share2 className="w-4 h-4" />}
                        />
                    </div>
                    <div>
                        <label className="text-sm font-medium text-white/60 mb-2 block">Приоритет</label>
                        <div className="flex gap-2">
                            {[0, 1, 2, 3].map(p => (
                                <button
                                    key={p}
                                    onClick={() => setPriority(p)}
                                    className={`flex-1 py-2.5 rounded-lg border font-bold text-sm transition-all ${priority === p
                                        ? p === 0 ? 'border-white/30 bg-white/10 text-white' :
                                            p === 1 ? 'border-green-500/50 bg-green-500/20 text-green-400' :
                                                p === 2 ? 'border-yellow-500/50 bg-yellow-500/20 text-yellow-400' :
                                                    'border-red-500/50 bg-red-500/20 text-red-400'
                                        : 'border-white/5 bg-white/5 text-white/40 hover:bg-white/10'
                                        }`}
                                >
                                    {p}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>

                <div>
                    <label className="text-sm font-medium text-white/60 mb-2 block">Ссылка на профиль</label>
                    <div className="flex gap-2">
                        <span className="bg-white/5 border border-white/10 rounded-xl px-4 flex items-center text-white/40 select-none">
                            {getPlatformPrefix(platform)}
                        </span>
                        <input type="text" className="flex-1 bg-black/20 border border-white/10 rounded-xl p-3 text-white focus:outline-none focus:border-orange-500/50 transition-colors" placeholder="channel" />
                    </div>
                </div>

                <div className="pt-4 flex justify-end">
                    <button className="px-8 py-3 bg-orange-500 hover:bg-orange-600 text-white font-bold rounded-xl shadow-lg shadow-orange-500/20 transition-all">
                        Добавить медиа
                    </button>
                </div>
            </div>
        </div>
    );
};

export default MediaRegistration;
