import React from 'react';
import { Settings, X, MapPin, AlertCircle, Save } from 'lucide-react';

interface StreamerSettingsModalProps {
    streamer: any;
    isOpen: boolean;
    onClose: () => void;
    onSave: (data: any) => Promise<void>;
}

const StreamerSettingsModal = ({ streamer, isOpen, onClose, onSave }: StreamerSettingsModalProps) => {
    const [priority, setPriority] = React.useState(streamer?.priority || 0);
    const [isPinned, setIsPinned] = React.useState(streamer?.is_pinned || false);
    const [pointsOverride, setPointsOverride] = React.useState(streamer?.stream_points_override || '');
    const [saving, setSaving] = React.useState(false);

    React.useEffect(() => {
        if (streamer) {
            setPriority(streamer.priority || 0);
            setIsPinned(streamer.is_pinned || false);
            setPointsOverride(streamer.stream_points_override || '');
        }
    }, [streamer]);

    if (!isOpen || !streamer) return null;

    const handleSave = async () => {
        setSaving(true);
        try {
            await onSave({
                priority,
                is_pinned: isPinned,
                stream_points_override: pointsOverride === '' ? null : Number(pointsOverride)
            });
            onClose();
        } catch (error) {
            console.error('Failed to save settings:', error);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]">
            <div className="bg-[#1e1e1e] border border-white/10 rounded-2xl w-full max-w-md shadow-2xl transform transition-all scale-100">
                <div className="flex items-center justify-between p-6 border-b border-white/5">
                    <h3 className="text-xl font-bold text-white flex items-center gap-2">
                        <Settings className="w-5 h-5 text-white/40" />
                        Настройки стримера
                    </h3>
                    <button
                        onClick={onClose}
                        className="p-2 hover:bg-white/5 rounded-lg text-white/40 hover:text-white transition-colors"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="p-6 space-y-6">
                    {/* Streamer Info */}
                    <div className="flex items-center gap-4 p-4 bg-white/5 rounded-xl border border-white/5">
                        <img
                            src={streamer.profile_image_url || streamer.stream_thumbnail_url}
                            alt={streamer.streamer_name}
                            className="w-12 h-12 rounded-full object-cover bg-[#121212]"
                        />
                        <div>
                            <div className="font-bold text-lg text-white">{streamer.streamer_name}</div>
                            <div className="text-sm text-white/40">ID: {streamer.streamer_id}</div>
                        </div>
                    </div>

                    {/* Priority Selection */}
                    <div>
                        <label className="text-sm font-medium text-white/60 mb-3 block">Приоритет</label>
                        <div className="grid grid-cols-4 gap-2">
                            {[0, 1, 2, 3].map((p) => (
                                <button
                                    key={p}
                                    onClick={() => setPriority(p)}
                                    className={`h-12 rounded-lg border-2 font-bold transition-all ${priority === p
                                        ? p === 1 ? 'bg-green-500/20 border-green-500 text-green-400'
                                            : p === 2 ? 'bg-yellow-500/20 border-yellow-500 text-yellow-400'
                                                : p === 3 ? 'bg-red-500/20 border-red-500 text-red-400'
                                                    : 'bg-white/20 border-white/40 text-white'
                                        : 'bg-transparent border-white/10 text-white/40 hover:border-white/20 hover:text-white/60'
                                        }`}
                                >
                                    {p}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Pin Toggle */}
                    <div
                        onClick={() => setIsPinned(!isPinned)}
                        className={`flex items-center gap-4 p-4 rounded-xl border cursor-pointer transition-all ${isPinned
                            ? 'bg-blue-500/10 border-blue-500/50'
                            : 'bg-white/5 border-white/5 hover:border-white/20'
                            }`}
                    >
                        <div className={`p-2 rounded-lg ${isPinned ? 'bg-blue-500 text-white' : 'bg-white/10 text-white/40'}`}>
                            <MapPin className="w-5 h-5" />
                        </div>
                        <div className="flex-1">
                            <div className={`font-medium ${isPinned ? 'text-blue-400' : 'text-white/80'}`}>Закрепить в начале</div>
                            <div className="text-xs text-white/40">Стример будет отображаться первым в списке</div>
                        </div>
                        <div className={`w-12 h-6 rounded-full p-1 transition-colors ${isPinned ? 'bg-blue-500' : 'bg-white/10'}`}>
                            <div className={`w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${isPinned ? 'translate-x-6' : 'translate-x-0'}`} />
                        </div>
                    </div>

                    {/* Points Override */}
                    <div>
                        <label className="text-sm font-medium text-white/60 mb-3 block">Переопределение баллы за стрим</label>
                        <div className="relative">
                            <input
                                type="number"
                                value={pointsOverride}
                                onChange={(e) => setPointsOverride(e.target.value)}
                                placeholder="По умолчанию (авто)"
                                className="w-full bg-black/20 border border-white/10 rounded-xl px-4 py-3 text-white placeholder:text-white/20 focus:outline-none focus:border-purple-500 transition-colors"
                            />
                            <div className="absolute right-4 top-1/2 -translate-y-1/2 text-white/20 text-sm">баллов</div>
                        </div>
                        <div className="flex items-center gap-2 mt-2 text-xs text-yellow-500/60">
                            <AlertCircle className="w-3 h-3" />
                            <span>Сбрасывается при окончании стрима</span>
                        </div>
                    </div>
                </div>

                <div className="p-6 border-t border-white/5 flex gap-3">
                    <button
                        onClick={onClose}
                        className="flex-1 px-4 py-3 rounded-xl font-semibold text-white/60 hover:text-white hover:bg-white/5 transition-colors"
                        disabled={saving}
                    >
                        Отмена
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={saving}
                        className="flex-[2] px-4 py-3 rounded-xl font-bold bg-[#3b82f6] hover:bg-[#2563eb] text-white transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {saving ? (
                            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        ) : (
                            <>
                                <Save className="w-5 h-5" />
                                Сохранить
                            </>
                        )}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default StreamerSettingsModal;
