
import { useState } from 'react';
import { CalendarPlus } from 'lucide-react';
import { CustomDatePicker, CustomTimePicker } from '../../../components/CustomInputs';
import NotificationToast from '../../../components/feedback/NotificationToast';
import { usePopupToast } from '../../../components/feedback/hooks';
import { getApiErrorMessage } from '../../../types/api';
import { getMskNow, getMskTodayStr } from '../../../utils/datetime';
import { apiFetch } from '../../../api/client';

const CreateEvent = () => {
    const { toast, showToast, closeToast } = usePopupToast(3000);
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

    const handleCreateEvent = async () => {
        if (!eventName || !description) {
            showToast('Заполните все обязательные поля', 'error');
            return;
        }

        setLoading(true);

        try {
            // Combine date and time if provided
            let startTime = null;
            if (date && time) {
                startTime = `${date}T${time}:00`;
                // Validate not in the past
                const startDate = new Date(startTime + '+03:00');
                const mskNow = getMskNow();
                if (startDate.getTime() < mskNow.getTime() - 60000) { // 1 min buffer
                    showToast('Дата и время начала не могут быть в прошлом', 'error');
                    setLoading(false);
                    return;
                }
            }

            const response = await apiFetch('/api/events', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    name: eventName,
                    description: description,
                    priority: priority,
                    pr_slots: prSlots,
                    required_pr_count: prSlots, // Use pr_slots as required count
                    start_time: startTime
                })
            });

            const data = await response.json().catch(() => ({} as unknown));

            if (!response.ok) {
                throw new Error(getApiErrorMessage(data, 'Ошибка при создании события'));
            }

            showToast('Событие успешно создано');
            // Reset form
            setEventName('');
            setDescription('');
            setDate('');
            setTime('');
            setPriority(0);
            setPrSlots(1);

        } catch (err: unknown) {
            showToast(err instanceof Error ? err.message : 'Произошла ошибка', 'error');
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

export default CreateEvent;
