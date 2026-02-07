import { useState, useEffect } from 'react';
import { Settings, X, Save, AlertCircle, Pin } from 'lucide-react';

interface EventSettingsModalProps {
    event: any;
    isOpen: boolean;
    onClose: () => void;
    onSave: (data: any) => Promise<void>;
}

const EventSettingsModal = ({ event, isOpen, onClose, onSave }: EventSettingsModalProps) => {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [priority, setPriority] = useState(0);
    const [prSlots, setPrSlots] = useState(1);
    const [isPinned, setIsPinned] = useState(false);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (event) {
            setName(event.name || '');
            setDescription(event.description || '');
            setPriority(event.priority || 0);
            setPrSlots(event.pr_slots || event.required_pr_count || 1);
            setIsPinned(event.is_pinned || false);
        }
    }, [event]);

    if (!isOpen || !event) return null;

    const handleSave = async () => {
        if (!name.trim()) return;

        setSaving(true);
        try {
            await onSave({
                name,
                description,
                priority,
                is_pinned: isPinned,
                required_pr_count: prSlots
            });
            onClose();
        } catch (error) {
            console.error('Failed to save event settings:', error);
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
                        Настройки события
                    </h3>
                    <button
                        onClick={onClose}
                        className="p-2 hover:bg-white/5 rounded-lg text-white/40 hover:text-white transition-colors"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="p-6 space-y-6">
                    {/* Pin Toggle */}
                    <div
                        onClick={() => setIsPinned(!isPinned)}
                        className={`flex items-center gap-4 p-4 rounded-xl border cursor-pointer transition-all ${isPinned
                            ? 'bg-blue-500/10 border-blue-500/50'
                            : 'bg-white/5 border-white/5 hover:border-white/20'
                            }`}
                    >
                        <div className={`p-2 rounded-lg ${isPinned ? 'bg-blue-500 text-white' : 'bg-white/10 text-white/40'}`}>
                            <Pin className="w-5 h-5" />
                        </div>
                        <div className="flex-1">
                            <div className={`font-medium ${isPinned ? 'text-blue-400' : 'text-white/80'}`}>Закрепить в начале</div>
                            <div className="text-xs text-white/40">Событие будет отображаться первым в списке</div>
                        </div>
                        <div className={`w-12 h-6 rounded-full p-1 transition-colors ${isPinned ? 'bg-blue-500' : 'bg-white/10'}`}>
                            <div className={`w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${isPinned ? 'translate-x-6' : 'translate-x-0'}`} />
                        </div>
                    </div>

                    {/* Name */}
                    <div>
                        <label className="text-sm font-medium text-white/60 mb-2 block">Название</label>
                        <input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            className="w-full bg-black/20 border border-white/10 rounded-xl px-4 py-3 text-white placeholder:text-white/20 focus:outline-none focus:border-purple-500 transition-colors"
                            placeholder="Название события"
                        />
                    </div>

                    {/* Description */}
                    <div>
                        <label className="text-sm font-medium text-white/60 mb-2 block">Описание</label>
                        <textarea
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            className="w-full h-24 bg-black/20 border border-white/10 rounded-xl px-4 py-3 text-white placeholder:text-white/20 focus:outline-none focus:border-purple-500 transition-colors resize-none"
                            placeholder="Описание события..."
                        />
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

                    {/* PR Slots */}
                    <div>
                        <label className="text-sm font-medium text-white/60 mb-3 block">Количество слотов (PR)</label>
                        <input
                            type="number"
                            min="1"
                            max="50"
                            value={prSlots}
                            onChange={(e) => setPrSlots(Math.max(1, parseInt(e.target.value) || 1))}
                            className="w-full bg-black/20 border border-white/10 rounded-xl px-4 py-3 text-white placeholder:text-white/20 focus:outline-none focus:border-purple-500 transition-colors"
                        />
                    </div>

                    <div className="flex items-center gap-2 text-xs text-yellow-500/60 p-3 bg-yellow-500/5 rounded-lg border border-yellow-500/10">
                        <AlertCircle className="w-4 h-4 shrink-0" />
                        <span>Изменения вступят в силу немедленно</span>
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
                        disabled={saving || !name.trim()}
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

export default EventSettingsModal;
