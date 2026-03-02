
import { useState } from 'react';
import { CalendarPlus, Check, AlertCircle } from 'lucide-react';
import { CustomDatePicker, CustomTimePicker } from '../../../components/CustomInputs';
import { getApiErrorMessage } from '../../../types/api';
import { getMskNow, getMskTodayStr } from '../../../utils/datetime';

const CreateEvent = () => {
    const [priority, setPriority] = useState(0);
    const [prSlots, setPrSlots] = useState(1);
    const [eventName, setEventName] = useState('');
    const [description, setDescription] = useState('');
    const [date, setDate] = useState(getMskTodayStr());
    const [time, setTime] = useState(() => {
        const now = getMskNow();
        const pad = (n: number) => String(n).padStart(2, '0');
        return `${pad(now.getHours())}:${pad(now.getMinutes())}`;
    });
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);

    const handleCreateEvent = async () => {
        if (!eventName || !description) {
            setMessage({ type: 'error', text: 'Заполните все обязательные поля' });
            return;
        }

        setLoading(true);
        setMessage(null);

        try {
            const token = localStorage.getItem('access_token');
            const stored = localStorage.getItem('user');
            const user = (stored ? JSON.parse(stored) : {}) as { discord_id?: string | number };

            // Combine date and time if provided
            let startTime = null;
            if (date && time) {
                startTime = `${date}T${time}:00`;
                // Validate not in the past
                const startDate = new Date(startTime + '+03:00');
                const mskNow = getMskNow();
                if (startDate.getTime() < mskNow.getTime() - 60000) { // 1 min buffer
                    setMessage({ type: 'error', text: 'Дата и время начала не могут быть в прошлом' });
                    setLoading(false);
                    return;
                }
            }

            const response = await fetch('/api/events', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    name: eventName,
                    description: description,
                    priority: priority,
                    pr_slots: prSlots,
                    required_pr_count: prSlots, // Use pr_slots as required count
                    start_time: startTime,
                    created_by: user.discord_id || 0
                })
            });

            const data = await response.json().catch(() => ({} as unknown));

            if (!response.ok) {
                throw new Error(getApiErrorMessage(data, 'Ошибка при создании события'));
            }

            setMessage({ type: 'success', text: 'Событие успешно создано' });
            // Reset form
            setEventName('');
            setDescription('');
            setDate('');
            setTime('');
            setPriority(0);
            setPrSlots(1);

        } catch (err: unknown) {
            setMessage({ type: 'error', text: err instanceof Error ? err.message : 'Произошла ошибка' });
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="space-y-8 animate-[fadeIn_0.3s_ease-in-out]">
            <div className="flex items-center gap-4 border-b border-white/10 pb-6">
                <div className="w-12 h-12 rounded-xl bg-purple-500/20 text-purple-400 flex items-center justify-center border border-purple-500/30">
                    <CalendarPlus className="w-6 h-6" />
                </div>
                <div>
                    <h2 className="text-2xl font-bold text-white">Новое событие</h2>
                    <p className="text-white/60">Создание нового мероприятия или собрания</p>
                </div>
            </div>

            <div className="bg-[#1e1e1e] border border-white/5 rounded-2xl p-6">
                {message && (
                    <div className={`px-4 py-3 rounded-xl flex items-center gap-3 ${message.type === 'success' ? 'bg-green-500/10 border border-green-500/20 text-green-400' : 'bg-red-500/10 border border-red-500/20 text-red-400'} mb-6`}>
                        {message.type === 'success' ? <Check className="w-5 h-5" /> : <AlertCircle className="w-5 h-5" />}
                        {message.text}
                    </div>
                )}

                <div className="grid grid-cols-2 gap-8">
                    <div className="space-y-6">
                        <div>
                            <label className="text-sm font-medium text-white/60 mb-2 block">Название события</label>
                            <input
                                type="text"
                                className="w-full bg-[#2a2a2a] border border-white/5 rounded-xl p-3 text-white focus:outline-none focus:border-purple-500/50 transition-colors"
                                placeholder="Например: Собрание"
                                value={eventName}
                                onChange={(e) => setEventName(e.target.value)}
                            />
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="text-sm font-medium text-white/60 mb-2 block">Дата начала</label>
                                <CustomDatePicker value={date} onChange={setDate} placeholder="ДД.ММ.ГГГГ" />
                            </div>
                            <div>
                                <label className="text-sm font-medium text-white/60 mb-2 block">Время</label>
                                <CustomTimePicker value={time} onChange={setTime} placeholder="--:--" />
                            </div>
                        </div>
                    </div>

                    <div className="space-y-6">
                        <div>
                            <label className="text-sm font-medium text-white/60 mb-2 block">Описание</label>
                            <textarea
                                className="w-full h-32 bg-[#2a2a2a] border border-white/5 rounded-xl p-3 text-white focus:outline-none focus:border-purple-500/50 transition-colors resize-none"
                                placeholder="Краткое описание события..."
                                value={description}
                                onChange={(e) => setDescription(e.target.value)}
                            />
                        </div>
                    </div>
                </div>

                {/* Priority Selector */}
                <div className="mt-6">
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

                {/* PR Slots Input */}
                <div className="mt-6">
                    <label className="text-sm font-medium text-white/60 mb-2 block">Количество слотов для PR</label>
                    <input
                        type="number"
                        min="1"
                        className="w-full bg-[#2a2a2a] border border-white/5 rounded-xl p-3 text-white focus:outline-none focus:border-purple-500/50 transition-colors"
                        placeholder="1"
                        value={prSlots}
                        onChange={(e) => setPrSlots(Math.max(1, parseInt(e.target.value) || 1))}
                    />
                </div>

                <div className="flex justify-end pt-4">
                    <button
                        onClick={handleCreateEvent}
                        disabled={loading}
                        className={`px-8 py-3 bg-purple-500 hover:bg-purple-600 text-white font-bold rounded-xl shadow-lg shadow-purple-500/20 transition-all ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                        {loading ? 'Создание...' : 'Создать событие'}
                    </button>
                </div>
            </div>
        </div>
    );
}

export default CreateEvent;
