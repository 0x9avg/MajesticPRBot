import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, X, Pencil, Clock, Save, RotateCcw } from 'lucide-react';
import { unwrapApiData, getApiErrorMessage } from '../../../types/api';
import { CustomDatePicker, CustomTimePicker } from '../../../components/CustomInputs';
import { formatMskToLocal } from '../../../utils/datetime';
import { apiFetch } from '../../../api/client';

/** Split 'YYYY-MM-DDTHH:mm' into { date: 'YYYY-MM-DD', time: 'HH:mm' } */
const splitDateTime = (combined: string) => {
    const [date = '', time = ''] = combined.split('T');
    return { date, time };
};

/** Merge date and time parts back into 'YYYY-MM-DDTHH:mm' */
const mergeDateTimePart = (current: string, part: 'date' | 'time', value: string) => {
    const { date, time } = splitDateTime(current);
    if (part === 'date') return value ? `${value}T${time || '00:00'}` : '';
    return date ? `${date}T${value || '00:00'}` : '';
};

interface PendingRequest {
    id: number;
    name: string;
    description: string;
    priority: number;
    requested_by: string;
    requester_nickname: string | null;
    start_time: string | null;
    session_started_at: string | null;
    session_ended_at: string | null;
    session_duration_seconds: number | null;
    is_active: boolean;
}

function formatDuration(seconds: number | null): string {
    if (!seconds || seconds <= 0) return '—';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `${h}ч ${m}м`;
    if (m > 0) return `${m}м ${s}с`;
    return `${s}с`;
}

function formatDatetime(dt: string | null): string {
    return formatMskToLocal(dt, { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export default function PendingRequests() {
    const navigate = useNavigate();
    const [requests, setRequests] = React.useState<PendingRequest[]>([]);
    const [loading, setLoading] = React.useState(true);
    const [actionLoading, setActionLoading] = React.useState<number | null>(null);
    const [error, setError] = React.useState<string | null>(null);
    const [editingId, setEditingId] = React.useState<number | null>(null);
    const [editForm, setEditForm] = React.useState<{ name: string; description: string; priority: number; start_time: string; end_time: string }>({
        name: '', description: '', priority: 0, start_time: '', end_time: '',
    });

    const fetchRequests = async () => {
        try {
            const response = await apiFetch('/api/events/pending');
            if (response.ok) {
                const json = await response.json() as unknown;
                const data = unwrapApiData<PendingRequest[]>(json);
                setRequests(Array.isArray(data) ? data : []);
            }
        } catch (e) {
            console.error('Failed to fetch pending requests:', e);
        } finally {
            setLoading(false);
        }
    };

    React.useEffect(() => {
        void fetchRequests();
        const interval = setInterval(() => void fetchRequests(), 15000);
        return () => clearInterval(interval);
    }, []);

    const startEditing = (req: PendingRequest) => {
        setEditingId(req.id);
        // Convert ISO timestamps to datetime-local format for inputs
        const toLocal = (dt: string | null) => {
            if (!dt) return '';
            return dt.length >= 16 ? dt.substring(0, 16) : dt;
        };
        setEditForm({
            name: req.name,
            description: req.description || '',
            priority: req.priority,
            start_time: toLocal(req.session_started_at || req.start_time),
            end_time: toLocal(req.session_ended_at),
        });
    };

    const cancelEditing = () => {
        setEditingId(null);
        setEditForm({ name: '', description: '', priority: 0, start_time: '', end_time: '' });
    };

    const handleSave = async (id: number) => {
        setActionLoading(id);
        setError(null);
        try {
            const body: Record<string, unknown> = {
                name: editForm.name,
                description: editForm.description,
                priority: editForm.priority,
            };
            if (editForm.start_time) {
                body.start_time = editForm.start_time.length === 16 ? editForm.start_time + ':00' : editForm.start_time;
            }
            if (editForm.end_time) {
                body.end_time = editForm.end_time.length === 16 ? editForm.end_time + ':00' : editForm.end_time;
            }
            const response = await apiFetch(`/api/events/${id}/pending`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (response.ok) {
                setEditingId(null);
                await fetchRequests();
            } else {
                const err = await response.json().catch(() => ({} as unknown));
                setError(getApiErrorMessage(err, 'Не удалось сохранить изменения'));
            }
        } catch (e) {
            console.error('Error saving:', e);
            setError('Ошибка при сохранении');
        } finally {
            setActionLoading(null);
        }
    };

    const handleApprove = async (id: number) => {
        setActionLoading(id);
        setError(null);
        try {
            const response = await apiFetch(`/api/events/${id}/approve`, {
                method: 'POST',
            });
            if (response.ok) {
                setEditingId(null);
                await fetchRequests();
            } else {
                const err = await response.json().catch(() => ({} as unknown));
                setError(getApiErrorMessage(err, 'Не удалось одобрить'));
            }
        } catch (e) {
            console.error('Error approving:', e);
            setError('Ошибка при одобрении');
        } finally {
            setActionLoading(null);
        }
    };

    const handleReject = async (id: number) => {
        if (!window.confirm('Отклонить этот запрос? Сессия будет завершена без зачисления баллов.')) return;
        setActionLoading(id);
        setError(null);
        try {
            const response = await apiFetch(`/api/events/${id}/reject`, {
                method: 'POST',
            });
            if (response.ok) {
                await fetchRequests();
            } else {
                const err = await response.json().catch(() => ({} as unknown));
                setError(getApiErrorMessage(err, 'Не удалось отклонить'));
            }
        } catch (e) {
            console.error('Error rejecting:', e);
            setError('Ошибка при отклонении');
        } finally {
            setActionLoading(null);
        }
    };

    const priorityLabel = (p: number) => {
        const colors = [
            'bg-white/10 text-white/60 border-white/20',
            'bg-green-500/20 text-green-400 border-green-500/30',
            'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
            'bg-red-500/20 text-red-400 border-red-500/30',
        ];
        return colors[p] || colors[0];
    };

    if (loading) {
        return <div className="text-white/40 text-center py-8">Загрузка...</div>;
    }

    return (
        <div>
            <h2 className="text-2xl font-bold text-white mb-6 flex items-center gap-2">
                <Clock className="w-6 h-6 text-amber-400" />
                Неподтвержденные спеки
                {requests.length > 0 && (
                    <span className="ml-2 px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 text-sm font-semibold">
                        {requests.length}
                    </span>
                )}
            </h2>

            {error && (
                <div className="mb-4 px-4 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                    {error}
                </div>
            )}

            {requests.length === 0 ? (
                <div className="text-white/40 text-center py-12 bg-white/5 rounded-2xl border border-white/5">
                    Нет неподтвержденных запросов
                </div>
            ) : (
                <div className="overflow-visible rounded-2xl border border-white/5">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-white/10 bg-white/5">
                                <th className="text-left text-white/50 font-medium px-4 py-3">Ассистент</th>
                                <th className="text-left text-white/50 font-medium px-4 py-3">Название</th>
                                <th className="text-left text-white/50 font-medium px-4 py-3">Описание</th>
                                <th className="text-left text-white/50 font-medium px-4 py-3">Начало</th>
                                <th className="text-left text-white/50 font-medium px-4 py-3">Конец</th>
                                <th className="text-left text-white/50 font-medium px-4 py-3">Длительность</th>
                                <th className="text-center text-white/50 font-medium px-4 py-3">Приоритет</th>
                                <th className="text-center text-white/50 font-medium px-4 py-3">Действия</th>
                            </tr>
                        </thead>
                        <tbody>
                            {requests.map((req) => {
                                const isEditing = editingId === req.id;
                                const isActionLoading = actionLoading === req.id;
                                return (
                                    <tr key={req.id} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                                        <td className="px-4 py-3">
                                            <span
                                                className="text-blue-400 font-semibold cursor-pointer hover:text-blue-300 transition-colors"
                                                onClick={() => navigate(`/assistants/${req.requested_by}`)}
                                                title="Перейти в профиль"
                                            >
                                                @{req.requester_nickname || req.requested_by}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3">
                                            {isEditing ? (
                                                <input
                                                    type="text"
                                                    value={editForm.name}
                                                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                                                    className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-white text-sm w-full focus:outline-none focus:border-amber-500/50"
                                                    maxLength={100}
                                                />
                                            ) : (
                                                <span className="text-white font-medium">{req.name}</span>
                                            )}
                                        </td>
                                        <td className="px-4 py-3 max-w-[200px]">
                                            {isEditing ? (
                                                <input
                                                    type="text"
                                                    value={editForm.description}
                                                    onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                                                    className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-white text-sm w-full focus:outline-none focus:border-amber-500/50"
                                                    maxLength={1000}
                                                />
                                            ) : (
                                                <span className="text-white/60 truncate block">{req.description || '—'}</span>
                                            )}
                                        </td>
                                        <td className="px-4 py-3 text-white/60 whitespace-nowrap">
                                            {isEditing ? (
                                                <div className="flex gap-1">
                                                    <CustomDatePicker
                                                        value={splitDateTime(editForm.start_time).date}
                                                        onChange={(d) => setEditForm((prev) => ({ ...prev, start_time: mergeDateTimePart(prev.start_time, 'date', d) }))}
                                                        placeholder="Дата"
                                                    />
                                                    <CustomTimePicker
                                                        value={splitDateTime(editForm.start_time).time}
                                                        onChange={(t) => setEditForm((prev) => ({ ...prev, start_time: mergeDateTimePart(prev.start_time, 'time', t) }))}
                                                        placeholder="Время"
                                                    />
                                                </div>
                                            ) : (
                                                formatDatetime(req.session_started_at || req.start_time)
                                            )}
                                        </td>
                                        <td className="px-4 py-3 text-white/60 whitespace-nowrap">
                                            {isEditing ? (
                                                <div className="flex gap-1">
                                                    <CustomDatePicker
                                                        value={splitDateTime(editForm.end_time).date}
                                                        onChange={(d) => setEditForm((prev) => ({ ...prev, end_time: mergeDateTimePart(prev.end_time, 'date', d) }))}
                                                        placeholder="Дата"
                                                    />
                                                    <CustomTimePicker
                                                        value={splitDateTime(editForm.end_time).time}
                                                        onChange={(t) => setEditForm((prev) => ({ ...prev, end_time: mergeDateTimePart(prev.end_time, 'time', t) }))}
                                                        placeholder="Время"
                                                    />
                                                </div>
                                            ) : (
                                                formatDatetime(req.session_ended_at)
                                            )}
                                        </td>
                                        <td className="px-4 py-3 text-white/60 whitespace-nowrap">
                                            {req.session_ended_at
                                                ? formatDuration(req.session_duration_seconds)
                                                : req.is_active
                                                    ? <span className="text-emerald-400 text-xs font-medium">В процессе</span>
                                                    : '—'
                                            }
                                        </td>
                                        <td className="px-4 py-3 text-center">
                                            {isEditing ? (
                                                <div className="flex gap-1 justify-center">
                                                    {[0, 1, 2, 3].map((p) => (
                                                        <button
                                                            key={p}
                                                            onClick={() => setEditForm({ ...editForm, priority: p })}
                                                            className={`w-7 h-7 rounded-md text-xs font-bold border transition-colors ${editForm.priority === p ? priorityLabel(p) : 'bg-white/5 text-white/30 border-white/10 hover:bg-white/10'
                                                                }`}
                                                        >
                                                            {p}
                                                        </button>
                                                    ))}
                                                </div>
                                            ) : (
                                                <span className={`inline-flex items-center justify-center w-7 h-7 rounded-md text-xs font-bold border ${priorityLabel(req.priority)}`}>
                                                    {req.priority}
                                                </span>
                                            )}
                                        </td>
                                        <td className="px-4 py-3">
                                            <div className="flex items-center justify-center gap-1">
                                                {isEditing ? (
                                                    <>
                                                        <button
                                                            onClick={() => void handleSave(req.id)}
                                                            disabled={isActionLoading}
                                                            className="p-1.5 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400 hover:bg-blue-500/20 transition-colors disabled:opacity-50"
                                                            title="Сохранить изменения"
                                                        >
                                                            <Save className="w-4 h-4" />
                                                        </button>
                                                        <button
                                                            onClick={cancelEditing}
                                                            className="p-1.5 rounded-lg bg-white/5 border border-white/10 text-white/40 hover:bg-white/10 transition-colors"
                                                            title="Отменить редактирование"
                                                        >
                                                            <RotateCcw className="w-4 h-4" />
                                                        </button>
                                                    </>
                                                ) : (
                                                    <>
                                                        <button
                                                            onClick={() => startEditing(req)}
                                                            className="p-1.5 rounded-lg bg-white/5 border border-white/10 text-white/40 hover:text-amber-400 hover:bg-amber-500/10 hover:border-amber-500/20 transition-colors"
                                                            title="Редактировать"
                                                        >
                                                            <Pencil className="w-4 h-4" />
                                                        </button>
                                                        <button
                                                            onClick={() => void handleApprove(req.id)}
                                                            disabled={isActionLoading}
                                                            className="p-1.5 rounded-lg bg-green-500/10 border border-green-500/20 text-green-400 hover:bg-green-500/20 transition-colors disabled:opacity-50"
                                                            title="Одобрить"
                                                        >
                                                            <Check className="w-4 h-4" />
                                                        </button>
                                                        <button
                                                            onClick={() => void handleReject(req.id)}
                                                            disabled={isActionLoading}
                                                            className="p-1.5 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50"
                                                            title="Отклонить"
                                                        >
                                                            <X className="w-4 h-4" />
                                                        </button>
                                                    </>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )
            }
        </div >
    );
}
