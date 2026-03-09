import React from 'react';
import { ChevronLeft, ChevronRight, Copy, ExternalLink, Filter, History, Pencil, Plus, Trash2 } from 'lucide-react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { CustomDatePicker, CustomSelect } from '../../components/CustomInputs';
import ConfirmDialog from '../../components/feedback/ConfirmDialog';
import NotificationToast from '../../components/feedback/NotificationToast';
import { useConfirmDialog, usePopupToast } from '../../components/feedback/hooks';
import type { OutletUserContext } from '../../types/auth';
import type {
    PunishmentReturnCreateInput,
    PunishmentReturnHistoryItem,
    PunishmentReturnQueueItem,
    PunishmentReturnUpdateInput,
} from '../../types/domain';
import { unwrapApiData, getApiErrorMessage } from '../../types/api';
import { apiFetch } from '../../api/client';
import { formatMskToLocal } from '../../utils/datetime';
import {
    formatCommandPairLabel,
    formatPunishmentLabel,
    formatReturnServerLabel,
    RETURN_PUNISHMENT_OPTIONS,
    RETURN_REASON_OPTIONS,
    RETURN_SERVER_OPTIONS,
} from './constants';

type ReturnsTab = 'queue' | 'history';
type ReturnFormState = {
    punishment_type: 'jail' | 'mute';
    static: string;
    server: string;
    duration: string;
    remove_reason: 'На стрим' | 'На видео';
    discord_message_url: string;
};

type HistoryPayload = {
    items: PunishmentReturnHistoryItem[];
    total: number;
    page: number;
    pages: number;
};

type HistoryFiltersState = {
    static: string;
    server: string;
    removed_by: string;
    completed_by: string;
    date_from: string;
    date_to: string;
    punishment_type: string;
};

const emptyFormState: ReturnFormState = {
    punishment_type: 'jail',
    static: '',
    server: '1',
    duration: '',
    remove_reason: 'На стрим',
    discord_message_url: '',
};

const emptyHistoryFilters: HistoryFiltersState = {
    static: '',
    server: '',
    removed_by: '',
    completed_by: '',
    date_from: '',
    date_to: '',
    punishment_type: '',
};

function buildRemoveCommand(
    punishmentType: 'jail' | 'mute',
    staticValue: string,
    removeReason: 'На стрим' | 'На видео',
    actorName: string,
): string {
    const command = punishmentType === 'jail' ? '/unjail' : '/unmute';
    const resolvedStatic = staticValue || '0';
    return `${command} ${resolvedStatic} ${removeReason} by ${actorName}`;
}

function buildReturnCommand(
    punishmentType: 'jail' | 'mute',
    staticValue: string,
    durationValue: string,
    actorName: string,
): string {
    const command = punishmentType === 'jail' ? '/ajail' : '/mute';
    const resolvedStatic = staticValue || '0';
    const resolvedDuration = Number(durationValue || 0) * 2;
    return `${command} ${resolvedStatic} ${resolvedDuration} Возврат наказания by ${actorName}`;
}

function getPageNumbers(totalPages: number, currentPage: number) {
    const pages: Array<number | '...'> = [];

    if (totalPages <= 7) {
        for (let i = 1; i <= totalPages; i += 1) pages.push(i);
        return pages;
    }

    pages.push(1);
    if (currentPage > 3) pages.push('...');
    for (let i = Math.max(2, currentPage - 1); i <= Math.min(totalPages - 1, currentPage + 1); i += 1) {
        pages.push(i);
    }
    if (currentPage < totalPages - 2) pages.push('...');
    pages.push(totalPages);
    return pages;
}

interface ReturnFormModalProps {
    isOpen: boolean;
    title: string;
    submitLabel: string;
    actorName: string;
    form: ReturnFormState;
    loading: boolean;
    existingRecord?: PunishmentReturnQueueItem | PunishmentReturnHistoryItem | null;
    onClose: () => void;
    onChange: (updates: Partial<ReturnFormState>) => void;
    onCopyCommand: (value: string) => void;
    onSubmit: () => void;
}

function ReturnFormModal({
    isOpen,
    title,
    submitLabel,
    actorName,
    form,
    loading,
    existingRecord,
    onClose,
    onChange,
    onCopyCommand,
    onSubmit,
}: ReturnFormModalProps) {
    if (!isOpen) return null;

    const removeCommandActor = existingRecord?.removed_by_name || actorName;
    const previewTimestamp = existingRecord?.removed_at
        ? formatMskToLocal(existingRecord.removed_at)
        : formatMskToLocal(new Date().toISOString());
    const showReturnCommandPreview = Boolean(existingRecord);
    const removeCommand = buildRemoveCommand(form.punishment_type, form.static, form.remove_reason, removeCommandActor);
    const returnCommandActor =
        existingRecord?.completed_by_name ||
        existingRecord?.claimed_by_name ||
        actorName;
    const returnCommand = buildReturnCommand(form.punishment_type, form.static, form.duration, returnCommandActor);

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-[fadeIn_0.2s_ease-out]">
            <div className="w-full max-w-4xl bg-[#1e1e1e] border border-white/10 rounded-3xl shadow-2xl overflow-hidden">
                <div className="flex items-center justify-between px-6 py-5 border-b border-white/5">
                    <div>
                        <h3 className="text-2xl font-bold text-white">{title}</h3>
                        <p className="text-sm text-white/40 mt-1">Проверь поля и сохраните запись в общий список возвратов.</p>
                    </div>
                    <button
                        onClick={onClose}
                        className="px-3 py-2 rounded-xl border border-white/10 text-white/50 hover:text-white hover:bg-white/5 transition-colors"
                    >
                        Закрыть
                    </button>
                </div>

                <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-0">
                    <div className="p-6 border-r border-white/5 space-y-5">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label className="text-xs font-medium text-white/40 mb-1 block">Тип наказания</label>
                                <CustomSelect
                                    value={form.punishment_type}
                                    onChange={(value) => {
                                        if (typeof value === 'string') {
                                            onChange({ punishment_type: value as 'jail' | 'mute' });
                                        }
                                    }}
                                    options={RETURN_PUNISHMENT_OPTIONS.map((item) => ({ value: item.value, label: item.label }))}
                                />
                            </div>

                            <div>
                                <label className="text-xs font-medium text-white/40 mb-1 block">Сервер</label>
                                <CustomSelect
                                    value={form.server}
                                    onChange={(value) => {
                                        if (typeof value === 'string') {
                                            onChange({ server: value });
                                        }
                                    }}
                                    options={RETURN_SERVER_OPTIONS}
                                />
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label className="text-xs font-medium text-white/40 mb-1 block">Статик</label>
                                <input
                                    type="number"
                                    min="1"
                                    value={form.static}
                                    onChange={(e) => onChange({ static: e.target.value })}
                                    className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                    placeholder="Например, 138254"
                                />
                            </div>

                            <div>
                                <label className="text-xs font-medium text-white/40 mb-1 block">Время наказания</label>
                                <input
                                    type="number"
                                    min="1"
                                    value={form.duration}
                                    onChange={(e) => onChange({ duration: e.target.value })}
                                    className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                    placeholder="Например, 30"
                                />
                            </div>
                        </div>

                        <div>
                            <label className="text-xs font-medium text-white/40 mb-1 block">Причина снятия</label>
                            <CustomSelect
                                value={form.remove_reason}
                                onChange={(value) => {
                                    if (typeof value === 'string') {
                                        onChange({ remove_reason: value as 'На стрим' | 'На видео' });
                                    }
                                }}
                                options={RETURN_REASON_OPTIONS.map((item) => ({ value: item.value, label: item.label }))}
                            />
                        </div>

                        <div>
                            <label className="text-xs font-medium text-white/40 mb-1 block">Ссылка на Discord</label>
                            <input
                                type="url"
                                value={form.discord_message_url}
                                onChange={(e) => onChange({ discord_message_url: e.target.value })}
                                className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                placeholder="https://discord.com/channels/..."
                            />
                        </div>
                    </div>

                    <div className="p-6 bg-white/[0.02] space-y-4">
                        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 space-y-3">
                            <div>
                                <div className="text-xs uppercase tracking-wide text-white/30 mb-1">PR Assistant</div>
                                <div className="text-white font-semibold">{removeCommandActor}</div>
                            </div>
                            <div>
                                <div className="text-xs uppercase tracking-wide text-white/30 mb-1">Время снятия</div>
                                <div className="text-white/80">{previewTimestamp}</div>
                            </div>
                            <div>
                                <div className="text-xs uppercase tracking-wide text-white/30 mb-1">Сервер</div>
                                <div className="text-white/80">{formatReturnServerLabel(form.server)}</div>
                            </div>
                            <div>
                                <div className="text-xs uppercase tracking-wide text-white/30 mb-1">Наказание</div>
                                <div className="text-white/80">{formatCommandPairLabel(form.punishment_type)}</div>
                            </div>
                        </div>

                        <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                            <div className="flex items-center justify-between gap-3 mb-2">
                                <div className="text-xs uppercase tracking-wide text-white/30">Команда снятия</div>
                                <button
                                    onClick={() => onCopyCommand(removeCommand)}
                                    className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/60 hover:text-white transition-colors text-xs"
                                    title="Скопировать команду"
                                >
                                    <Copy className="w-3.5 h-3.5" />
                                    Скопировать
                                </button>
                            </div>
                            <pre className="whitespace-pre-wrap break-all text-sm text-blue-300 font-mono">
                                {removeCommand}
                            </pre>
                        </div>

                        {showReturnCommandPreview && (
                            <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                                <div className="flex items-center justify-between gap-3 mb-2">
                                    <div className="text-xs uppercase tracking-wide text-white/30">Команда возврата</div>
                                    <button
                                        onClick={() => onCopyCommand(returnCommand)}
                                        className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/60 hover:text-white transition-colors text-xs"
                                        title="Скопировать команду"
                                    >
                                        <Copy className="w-3.5 h-3.5" />
                                        Скопировать
                                    </button>
                                </div>
                                <pre className="whitespace-pre-wrap break-all text-sm text-emerald-300 font-mono">
                                    {returnCommand}
                                </pre>
                            </div>
                        )}

                        <div className="flex gap-3 pt-2">
                            <button
                                onClick={onSubmit}
                                disabled={loading}
                                className="flex-1 px-4 py-3 rounded-xl bg-blue-500/15 border border-blue-500/30 text-blue-300 font-semibold hover:bg-blue-500/25 transition-colors disabled:opacity-50"
                            >
                                {loading ? 'Сохранение...' : submitLabel}
                            </button>
                            <button
                                onClick={onClose}
                                className="px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white/70 hover:text-white hover:bg-white/10 transition-colors"
                            >
                                Отмена
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

function StatusBadge({
    label,
    actorId,
    actorName,
    onActorClick,
}: {
    label: string;
    actorId?: string | null;
    actorName?: string | null;
    onActorClick?: (actorId: string) => void;
}) {
    let className = 'bg-white/10 text-white/70 border-white/10';
    if (label.startsWith('Готово')) className = 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30';
    if (label.startsWith('Ждет')) className = 'bg-amber-500/15 text-amber-300 border-amber-500/30';
    if (label.startsWith('В работе')) className = 'bg-blue-500/15 text-blue-300 border-blue-500/30';
    if (label.startsWith('Выполнено')) className = 'bg-white/10 text-white/70 border-white/10';

    const canOpenActor = label.startsWith('В работе') && !!actorId && !!actorName && !!onActorClick;

    return (
        <span className={`inline-flex px-3 py-1 rounded-full border text-xs font-semibold whitespace-nowrap ${className}`}>
            {canOpenActor ? (
                <>
                    <span>В работе:&nbsp;</span>
                    <button
                        type="button"
                        onClick={() => onActorClick(actorId)}
                        className="font-semibold underline decoration-white/30 underline-offset-2 hover:decoration-current transition-colors"
                    >
                        {actorName}
                    </button>
                </>
            ) : (
                label
            )}
        </span>
    );
}

function CommandBlock({
    lines,
    onCopy,
}: {
    lines: Array<{ label?: string; value: string }>;
    onCopy: (value: string) => void;
}) {
    return (
        <div className="space-y-2">
            {lines.map((line, index) => (
                <div key={`${line.value}-${index}`} className="rounded-xl border border-white/10 bg-black/20 p-3">
                    {line.label && (
                        <div className="text-[10px] uppercase tracking-wide text-white/30 mb-1 whitespace-nowrap">{line.label}</div>
                    )}
                    <div className="flex items-start gap-2">
                        <pre className="flex-1 whitespace-nowrap overflow-x-visible text-xs text-white/80 font-mono">{line.value}</pre>
                        <button
                            onClick={() => onCopy(line.value)}
                            className="p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/50 hover:text-white transition-colors shrink-0"
                            title="Скопировать команду"
                        >
                            <Copy className="w-3.5 h-3.5" />
                        </button>
                    </div>
                </div>
            ))}
        </div>
    );
}

export default function PunishmentReturns() {
    const { user } = useOutletContext<OutletUserContext>();
    const navigate = useNavigate();
    const { toast, showToast, closeToast } = usePopupToast(2200);
    const { confirm, dialogProps } = useConfirmDialog();
    const [activeTab, setActiveTab] = React.useState<ReturnsTab>('queue');
    const [queueItems, setQueueItems] = React.useState<PunishmentReturnQueueItem[]>([]);
    const [historyItems, setHistoryItems] = React.useState<PunishmentReturnHistoryItem[]>([]);
    const [queueLoading, setQueueLoading] = React.useState(true);
    const [historyLoading, setHistoryLoading] = React.useState(false);
    const [historyPage, setHistoryPage] = React.useState(1);
    const [historyTotalPages, setHistoryTotalPages] = React.useState(1);
    const [historyTotal, setHistoryTotal] = React.useState(0);
    const [historyFilters, setHistoryFilters] = React.useState<HistoryFiltersState>(emptyHistoryFilters);
    const [isCreateOpen, setIsCreateOpen] = React.useState(false);
    const [editingRecord, setEditingRecord] = React.useState<PunishmentReturnQueueItem | PunishmentReturnHistoryItem | null>(null);
    const [formState, setFormState] = React.useState<ReturnFormState>(emptyFormState);
    const [submitting, setSubmitting] = React.useState(false);
    const [deletingRecordId, setDeletingRecordId] = React.useState<string | null>(null);

    const actorName = user?.nickname || 'unknown';
    const canCreate = user?.permissions?.['returns.create'] === true;
    const canViewHistory = user?.permissions?.['returns.history.view'] === true;
    const historyFiltersRef = React.useRef<HistoryFiltersState>(historyFilters);

    React.useEffect(() => {
        historyFiltersRef.current = historyFilters;
    }, [historyFilters]);

    const openCreateModal = () => {
        setEditingRecord(null);
        setFormState(emptyFormState);
        setIsCreateOpen(true);
    };

    const openEditModal = (record: PunishmentReturnQueueItem | PunishmentReturnHistoryItem) => {
        setEditingRecord(record);
        setFormState({
            punishment_type: record.punishment_type,
            static: String(record.static),
            server: String(record.server),
            duration: String(record.duration),
            remove_reason: record.remove_reason,
            discord_message_url: record.discord_message_url ?? '',
        });
    };

    const closeFormModal = () => {
        setIsCreateOpen(false);
        setEditingRecord(null);
        setFormState(emptyFormState);
    };

    const copyCommand = async (value: string) => {
        try {
            await navigator.clipboard.writeText(value);
            showToast('Команда скопирована');
        } catch {
            showToast('Не удалось скопировать команду', 'error');
        }
    };

    const fetchQueue = React.useCallback(async () => {
        setQueueLoading(true);
        try {
            const response = await apiFetch('/api/returns/queue');
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payload, 'Не удалось загрузить очередь возвратов'));
            }
            const json = await response.json() as unknown;
            const data = unwrapApiData<PunishmentReturnQueueItem[]>(json);
            setQueueItems(Array.isArray(data) ? data : []);
        } catch (error) {
            console.error('Failed to fetch returns queue:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось загрузить очередь возвратов', 'error');
        } finally {
            setQueueLoading(false);
        }
    }, [showToast]);

    const fetchHistory = React.useCallback(async (page = 1, filtersOverride?: HistoryFiltersState) => {
        setHistoryLoading(true);
        try {
            const activeFilters = filtersOverride ?? historyFiltersRef.current;
            const params = new URLSearchParams();
            params.append('page', String(page));
            params.append('limit', '20');
            if (activeFilters.static) params.append('static', activeFilters.static);
            if (activeFilters.server) params.append('server', activeFilters.server);
            if (activeFilters.removed_by) params.append('removed_by', activeFilters.removed_by);
            if (activeFilters.completed_by) params.append('completed_by', activeFilters.completed_by);
            if (activeFilters.date_from) params.append('date_from', activeFilters.date_from);
            if (activeFilters.date_to) params.append('date_to', activeFilters.date_to);
            if (activeFilters.punishment_type) params.append('punishment_type', activeFilters.punishment_type);

            const response = await apiFetch(`/api/returns/history?${params.toString()}`);
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payload, 'Не удалось загрузить историю возвратов'));
            }
            const json = await response.json() as unknown;
            const data = unwrapApiData<HistoryPayload>(json);
            setHistoryItems(data.items || []);
            setHistoryTotal(data.total || 0);
            setHistoryPage(data.page || 1);
            setHistoryTotalPages(data.pages || 1);
        } catch (error) {
            console.error('Failed to fetch returns history:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось загрузить историю возвратов', 'error');
        } finally {
            setHistoryLoading(false);
        }
    }, [showToast]);

    React.useEffect(() => {
        if (activeTab === 'queue') {
            void fetchQueue();
            const interval = window.setInterval(() => void fetchQueue(), 15000);
            return () => window.clearInterval(interval);
        }
        if (activeTab === 'history' && canViewHistory) {
            void fetchHistory(1);
        }
        return undefined;
    }, [activeTab, canViewHistory, fetchHistory, fetchQueue]);

    const submitForm = async () => {
        const parsedStatic = Number(formState.static);
        const parsedServer = Number(formState.server);
        const parsedDuration = Number(formState.duration);
        const discordMessageUrl = formState.discord_message_url.trim();

        if (
            !Number.isInteger(parsedStatic) ||
            parsedStatic <= 0 ||
            !Number.isInteger(parsedServer) ||
            parsedServer <= 0 ||
            parsedServer > 17 ||
            !Number.isInteger(parsedDuration) ||
            parsedDuration <= 0
        ) {
            showToast('Заполните корректно все обязательные поля', 'error');
            return;
        }

        const payload: PunishmentReturnCreateInput | PunishmentReturnUpdateInput = {
            punishment_type: formState.punishment_type,
            static: parsedStatic,
            server: parsedServer,
            duration: parsedDuration,
            remove_reason: formState.remove_reason,
            discord_message_url: discordMessageUrl || null,
        };

        setSubmitting(true);
        try {
            const response = await apiFetch(
                editingRecord ? `/api/returns/${editingRecord.id}` : '/api/returns',
                {
                    method: editingRecord ? 'PATCH' : 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                },
            );

            if (!response.ok) {
                const errorPayload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(errorPayload, 'Не удалось сохранить возврат'));
            }

            closeFormModal();
            showToast(editingRecord ? 'Возврат обновлен' : 'Возврат создан');
            await fetchQueue();
            if (activeTab === 'history' && canViewHistory) {
                await fetchHistory(historyPage);
            }
        } catch (error) {
            console.error('Failed to submit return form:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось сохранить возврат', 'error');
        } finally {
            setSubmitting(false);
        }
    };

    const deleteRecord = async (record: PunishmentReturnQueueItem | PunishmentReturnHistoryItem) => {
        setDeletingRecordId(record.id);
        try {
            const response = await apiFetch(`/api/returns/${record.id}`, {
                method: 'DELETE',
            });
            if (!response.ok) {
                const errorPayload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(errorPayload, 'Не удалось удалить возврат'));
            }
            showToast('Возврат удален');
            await fetchQueue();
            if (activeTab === 'history' && canViewHistory) {
                await fetchHistory(historyPage);
            }
        } catch (error) {
            console.error('Failed to delete return:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось удалить возврат', 'error');
        } finally {
            setDeletingRecordId(null);
        }
    };

    const requestDelete = async (record: PunishmentReturnQueueItem | PunishmentReturnHistoryItem) => {
        const confirmed = await confirm({
            title: 'Удалить возврат?',
            message: (
                <>
                    Запись для статика <span className="text-white font-semibold">{record.static}</span> на сервере{' '}
                    <span className="text-white font-semibold">{formatReturnServerLabel(record.server)}</span> будет удалена.
                </>
            ),
            tone: 'danger',
            confirmLabel: 'Удалить',
        });

        if (!confirmed) {
            return;
        }

        await deleteRecord(record);
    };

    const handleClaim = async (recordId: string) => {
        try {
            const response = await apiFetch(`/api/returns/${recordId}/claim`, {
                method: 'POST',
            });
            if (!response.ok) {
                const errorPayload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(errorPayload, 'Не удалось взять возврат в работу'));
            }
            showToast('Возврат взят в работу');
            await fetchQueue();
        } catch (error) {
            console.error('Failed to claim return:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось взять возврат в работу', 'error');
        }
    };

    const handleComplete = async (recordId: string) => {
        try {
            const response = await apiFetch(`/api/returns/${recordId}/complete`, {
                method: 'POST',
            });
            if (!response.ok) {
                const errorPayload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(errorPayload, 'Не удалось завершить возврат'));
            }
            showToast('Возврат завершен');
            await fetchQueue();
            if (canViewHistory) {
                await fetchHistory(1);
            }
        } catch (error) {
            console.error('Failed to complete return:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось завершить возврат', 'error');
        }
    };

    const handleRelease = async (recordId: string) => {
        try {
            const response = await apiFetch(`/api/returns/${recordId}/release`, {
                method: 'POST',
            });
            if (!response.ok) {
                const errorPayload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(errorPayload, 'Не удалось отпустить возврат'));
            }
            showToast('Возврат возвращен в очередь');
            await fetchQueue();
        } catch (error) {
            console.error('Failed to release return:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось отпустить возврат', 'error');
        }
    };

    const renderQueueActionButtons = (item: PunishmentReturnQueueItem) => {
        const buttons: React.ReactNode[] = [];

        if (item.can_claim) {
            buttons.push(
                <button
                    key="claim"
                    onClick={() => void handleClaim(item.id)}
                    className="px-3 py-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 transition-colors text-xs font-semibold whitespace-nowrap"
                >
                    Взять
                </button>,
            );
        } else if (item.can_complete) {
            buttons.push(
                <button
                    key="complete"
                    onClick={() => void handleComplete(item.id)}
                    className="px-3 py-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 transition-colors text-xs font-semibold whitespace-nowrap"
                >
                    Завершить
                </button>,
            );
            if (item.can_release) {
                buttons.push(
                    <button
                        key="release"
                        onClick={() => void handleRelease(item.id)}
                        className="px-3 py-1.5 rounded-lg border border-white/10 bg-white/5 text-white/70 hover:text-white hover:bg-white/10 transition-colors text-xs font-semibold whitespace-nowrap"
                    >
                        Отменить
                    </button>,
                );
            }
        } else if (item.status_label.startsWith('Ждет')) {
            buttons.push(
                <span
                    key="wait"
                    className="px-3 py-1.5 rounded-lg border border-white/10 bg-white/5 text-white/40 text-xs font-semibold whitespace-nowrap"
                >
                    Ждет
                </span>,
            );
        } else if (item.status_label.startsWith('В работе')) {
            buttons.push(
                <span
                    key="busy"
                    className="px-3 py-1.5 rounded-lg border border-white/10 bg-white/5 text-white/40 text-xs font-semibold whitespace-nowrap"
                >
                    Занято
                </span>,
            );
        }

        if (item.can_edit) {
            buttons.push(
                <button
                    key="edit"
                    onClick={() => openEditModal(item)}
                    className="p-2 rounded-lg border border-white/10 bg-white/5 text-white/50 hover:text-white hover:bg-white/10 transition-colors"
                    title="Редактировать"
                >
                    <Pencil className="w-3.5 h-3.5" />
                </button>,
            );
        }

        if (item.can_delete) {
            buttons.push(
                <button
                    key="delete"
                    onClick={() => void requestDelete(item)}
                    disabled={deletingRecordId === item.id}
                    className="p-2 rounded-lg border border-red-500/20 bg-red-500/10 text-red-300 hover:bg-red-500/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    title="Удалить"
                >
                    <Trash2 className="w-3.5 h-3.5" />
                </button>,
            );
        }

        return <div className="flex flex-nowrap items-center gap-2 justify-end min-w-max">{buttons}</div>;
    };

    const renderHistoryAdminButtons = (item: PunishmentReturnHistoryItem) => {
        if (!item.can_edit && !item.can_delete) return null;

        return (
            <div className="flex flex-nowrap items-center gap-2 shrink-0">
                {item.can_edit && (
                    <button
                        onClick={() => openEditModal(item)}
                        className="p-2 rounded-lg border border-white/10 bg-white/5 text-white/50 hover:text-white hover:bg-white/10 transition-colors"
                        title="Редактировать"
                    >
                        <Pencil className="w-3.5 h-3.5" />
                    </button>
                )}
                {item.can_delete && (
                    <button
                        onClick={() => void requestDelete(item)}
                        disabled={deletingRecordId === item.id}
                        className="p-2 rounded-lg border border-red-500/20 bg-red-500/10 text-red-300 hover:bg-red-500/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Удалить"
                    >
                        <Trash2 className="w-3.5 h-3.5" />
                    </button>
                )}
            </div>
        );
    };

    const punishmentTypeOptions = [
        { value: '', label: 'Все типы наказания' },
        ...RETURN_PUNISHMENT_OPTIONS.map((item) => ({ value: item.value, label: item.label })),
    ];

    return (
        <div className="space-y-6 animate-[fadeIn_0.5s_ease-in-out] -mx-[calc(50vw-50%)] px-6 lg:px-12 pr-10 lg:pr-16">
            <div className="flex items-center justify-between gap-4">
                <h2 className="text-3xl font-bold flex items-center gap-2">
                    <span className="w-1 h-8 bg-[#3b82f6] rounded-full inline-block"></span>
                    Возвраты
                </h2>
                {canCreate && (
                    <button
                        onClick={openCreateModal}
                        className="inline-flex items-center gap-2 px-4 py-3 rounded-xl border border-blue-500/20 bg-blue-500/10 text-blue-300 font-semibold hover:bg-blue-500/20 transition-colors"
                    >
                        <Plus className="w-4 h-4" />
                        Снять с возвратом
                    </button>
                )}
            </div>

            <div className="flex gap-2 border-b border-white/10 pb-2">
                <button
                    onClick={() => setActiveTab('queue')}
                    className={`px-6 py-3 rounded-t-lg font-semibold transition-all ${activeTab === 'queue'
                        ? 'bg-white/10 text-white border-b-2 border-blue-500'
                        : 'text-white/60 hover:text-white hover:bg-white/5'
                        }`}
                >
                    К возврату
                </button>
                {canViewHistory && (
                    <button
                        onClick={() => setActiveTab('history')}
                        className={`px-6 py-3 rounded-t-lg font-semibold transition-all ${activeTab === 'history'
                            ? 'bg-white/10 text-white border-b-2 border-blue-500'
                            : 'text-white/60 hover:text-white hover:bg-white/5'
                            }`}
                    >
                        История
                    </button>
                )}
            </div>

            {activeTab === 'queue' && (
                <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden">
                    {queueLoading ? (
                        <div className="p-10 text-center text-white/40">Загрузка очереди...</div>
                    ) : queueItems.length === 0 ? (
                        <div className="p-10 text-center text-white/40">Нет активных возвратов</div>
                    ) : (
                        <div className="overflow-visible">
                            <table className="w-full text-left border-collapse">
                                <thead className="bg-[#1a1a1a]/80 border-b border-white/5 text-xs text-white/40 font-bold uppercase tracking-wider">
                                    <tr>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">СТАТИК / СЕРВЕР</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">НАКАЗАНИЕ</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">СНЯЛ</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">ВРЕМЯ СНЯТИЯ</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">СТАТУС</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">DISCORD</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">КОМАНДА</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap text-right">ДЕЙСТВИЕ</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-white/5">
                                    {queueItems.map((item) => (
                                        <tr key={item.id} className="hover:bg-white/5 transition-colors align-top">
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <div className="font-bold text-white/90">{item.static}</div>
                                                <div className="text-xs text-white/40 mt-1">{formatReturnServerLabel(item.server)}</div>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <div className="font-bold text-white/90">{formatPunishmentLabel(item.punishment_type)}</div>
                                                <div className="text-xs text-white/40 mt-1">{formatCommandPairLabel(item.punishment_type)}</div>
                                                <div className="text-xs text-white/60 mt-2">
                                                    {item.duration} мин, {item.remove_reason}
                                                </div>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <div className="font-semibold text-white/80">{item.removed_by_name}</div>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <div className="text-sm text-white/70">{formatMskToLocal(item.removed_at)}</div>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <StatusBadge
                                                    label={item.status_label}
                                                    actorId={item.claimed_by_id}
                                                    actorName={item.claimed_by_name}
                                                    onActorClick={(actorId) => navigate(`/assistants/${actorId}`)}
                                                />
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                {item.discord_message_url ? (
                                                    <a
                                                        href={item.discord_message_url}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                        className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white/70 hover:text-white hover:bg-white/10 transition-colors text-xs font-semibold whitespace-nowrap"
                                                    >
                                                        Открыть
                                                        <ExternalLink className="w-3.5 h-3.5" />
                                                    </a>
                                                ) : (
                                                    <span className="inline-flex px-3 py-2 rounded-lg border border-white/10 bg-white/[0.03] text-white/35 text-xs font-semibold whitespace-nowrap">
                                                        —
                                                    </span>
                                                )}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <CommandBlock lines={[{ value: item.return_command }]} onCopy={(value) => void copyCommand(value)} />
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-right">
                                                {renderQueueActionButtons(item)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'history' && canViewHistory && (
                <div className="space-y-4">
                    <div className="relative z-50 bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-4 flex flex-wrap gap-4 items-end overflow-visible">
                        <div className="w-[180px]">
                            <label className="text-xs font-medium text-white/40 mb-1 block">Статик</label>
                            <input
                                type="number"
                                min="1"
                                value={historyFilters.static}
                                onChange={(e) => setHistoryFilters((prev) => ({ ...prev, static: e.target.value }))}
                                className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                placeholder="Все статики"
                            />
                        </div>

                        <div className="w-[200px]">
                            <label className="text-xs font-medium text-white/40 mb-1 block">Сервер</label>
                            <CustomSelect
                                value={historyFilters.server}
                                onChange={(value) => {
                                    if (typeof value === 'string') {
                                        setHistoryFilters((prev) => ({ ...prev, server: value }));
                                    }
                                }}
                                options={[{ value: '', label: 'Все серверы' }, ...RETURN_SERVER_OPTIONS]}
                                icon={<Filter className="w-4 h-4" />}
                            />
                        </div>

                        <div className="w-[220px]">
                            <label className="text-xs font-medium text-white/40 mb-1 block">Снял</label>
                            <input
                                type="text"
                                value={historyFilters.removed_by}
                                onChange={(e) => setHistoryFilters((prev) => ({ ...prev, removed_by: e.target.value }))}
                                className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                placeholder="Ник ассистента"
                            />
                        </div>

                        <div className="w-[220px]">
                            <label className="text-xs font-medium text-white/40 mb-1 block">Перевыдал</label>
                            <input
                                type="text"
                                value={historyFilters.completed_by}
                                onChange={(e) => setHistoryFilters((prev) => ({ ...prev, completed_by: e.target.value }))}
                                className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                placeholder="Ник ассистента"
                            />
                        </div>

                        <div className="w-[210px]">
                            <label className="text-xs font-medium text-white/40 mb-1 block">Тип наказания</label>
                            <CustomSelect
                                value={historyFilters.punishment_type}
                                onChange={(value) => {
                                    if (typeof value === 'string') {
                                        setHistoryFilters((prev) => ({ ...prev, punishment_type: value }));
                                    }
                                }}
                                options={punishmentTypeOptions}
                                icon={<History className="w-4 h-4" />}
                            />
                        </div>

                        <div>
                            <label className="text-xs font-medium text-white/40 mb-1 block">С даты</label>
                            <CustomDatePicker
                                value={historyFilters.date_from}
                                onChange={(value) => setHistoryFilters((prev) => ({ ...prev, date_from: value }))}
                            />
                        </div>

                        <div>
                            <label className="text-xs font-medium text-white/40 mb-1 block">По дату</label>
                            <CustomDatePicker
                                value={historyFilters.date_to}
                                onChange={(value) => setHistoryFilters((prev) => ({ ...prev, date_to: value }))}
                            />
                        </div>

                        <div className="flex gap-2">
                            <button
                                onClick={() => void fetchHistory(1)}
                                className="px-4 py-2 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 border border-blue-500/20 rounded-lg text-sm font-medium transition-colors"
                            >
                                Применить
                            </button>
                            <button
                                onClick={() => {
                                    setHistoryFilters(emptyHistoryFilters);
                                    void fetchHistory(1, emptyHistoryFilters);
                                }}
                                className="px-4 py-2 bg-white/5 hover:bg-white/10 text-white/60 hover:text-white border border-white/5 rounded-lg text-sm font-medium transition-colors"
                            >
                                Сброс
                            </button>
                        </div>
                    </div>

                    <div className="flex items-center justify-between text-sm text-white/40 px-1">
                        <span>Всего записей: <span className="text-white/80 font-semibold">{historyTotal}</span></span>
                        <span>Страница {historyPage} из {historyTotalPages}</span>
                    </div>

                    <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden">
                        {historyLoading ? (
                            <div className="p-10 text-center text-white/40">Загрузка истории...</div>
                        ) : historyItems.length === 0 ? (
                            <div className="p-10 text-center text-white/40">История пуста</div>
                        ) : (
                            <div className="overflow-visible">
                                <table className="w-full text-left border-collapse">
                                    <thead className="bg-[#1a1a1a]/80 border-b border-white/5 text-xs text-white/40 font-bold uppercase tracking-wider">
                                        <tr>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">СТАТИК / СЕРВЕР</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">НАКАЗАНИЕ</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">СНЯЛ</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">ВРЕМЯ СНЯТИЯ</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">ПЕРЕВЫДАЛ</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">ВРЕМЯ ПЕРЕВЫДАЧИ</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">DISCORD СООБЩЕНИЕ</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-white/5">
                                        {historyItems.map((item) => (
                                            <tr key={item.id} className="hover:bg-white/5 transition-colors align-top">
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="font-bold text-white/90">{item.static}</div>
                                                    <div className="text-xs text-white/40 mt-1">{formatReturnServerLabel(item.server)}</div>
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="font-bold text-white/90">{formatPunishmentLabel(item.punishment_type)}</div>
                                                    <div className="text-xs text-white/40 mt-1">{item.duration} мин, {item.remove_reason}</div>
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="font-semibold text-white/80">{item.removed_by_name}</div>
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="text-sm text-white/70">{formatMskToLocal(item.removed_at)}</div>
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="font-semibold text-white/80">{item.completed_by_name || '—'}</div>
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="text-sm text-white/70">{item.completed_at ? formatMskToLocal(item.completed_at) : '—'}</div>
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="flex items-center gap-2 w-full">
                                                        <div className="shrink-0">
                                                            {item.discord_message_url ? (
                                                                <a
                                                                    href={item.discord_message_url}
                                                                    target="_blank"
                                                                    rel="noreferrer"
                                                                    className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white/70 hover:text-white hover:bg-white/10 transition-colors text-xs font-semibold whitespace-nowrap"
                                                                >
                                                                    Открыть
                                                                    <ExternalLink className="w-3.5 h-3.5" />
                                                                </a>
                                                            ) : (
                                                                <span className="inline-flex px-3 py-2 rounded-lg border border-white/10 bg-white/[0.03] text-white/35 text-xs font-semibold whitespace-nowrap">
                                                                    —
                                                                </span>
                                                            )}
                                                        </div>
                                                        <div className="ml-auto">
                                                            {renderHistoryAdminButtons(item)}
                                                        </div>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>

                    {historyTotalPages > 1 && (
                        <div className="flex items-center justify-center gap-2">
                            <button
                                onClick={() => void fetchHistory(historyPage - 1)}
                                disabled={historyPage <= 1}
                                className="p-2 rounded-lg bg-white/5 border border-white/10 text-white/50 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-40"
                            >
                                <ChevronLeft className="w-4 h-4" />
                            </button>
                            {getPageNumbers(historyTotalPages, historyPage).map((page, index) => (
                                <button
                                    key={`${page}-${index}`}
                                    onClick={() => {
                                        if (typeof page === 'number') {
                                            void fetchHistory(page);
                                        }
                                    }}
                                    disabled={page === '...'}
                                    className={`min-w-10 px-3 py-2 rounded-lg border text-sm font-medium transition-colors ${page === historyPage
                                        ? 'bg-blue-500/15 border-blue-500/30 text-blue-300'
                                        : 'bg-white/5 border-white/10 text-white/60 hover:text-white hover:bg-white/10'
                                        } disabled:cursor-default disabled:hover:bg-white/5`}
                                >
                                    {page}
                                </button>
                            ))}
                            <button
                                onClick={() => void fetchHistory(historyPage + 1)}
                                disabled={historyPage >= historyTotalPages}
                                className="p-2 rounded-lg bg-white/5 border border-white/10 text-white/50 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-40"
                            >
                                <ChevronRight className="w-4 h-4" />
                            </button>
                        </div>
                    )}
                </div>
            )}

            <ReturnFormModal
                isOpen={isCreateOpen || !!editingRecord}
                title={editingRecord ? 'Редактировать возврат' : 'Снять с возвратом'}
                submitLabel={editingRecord ? 'Сохранить изменения' : 'Создать возврат'}
                actorName={actorName}
                form={formState}
                loading={submitting}
                existingRecord={editingRecord}
                onClose={closeFormModal}
                onChange={(updates) => setFormState((prev) => ({ ...prev, ...updates }))}
                onCopyCommand={(value) => void copyCommand(value)}
                onSubmit={() => void submitForm()}
            />

            <ConfirmDialog {...dialogProps} />

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
