import React from 'react';
import { ChevronLeft, ChevronRight, Copy, ExternalLink, Pencil, Plus, Trash2 } from 'lucide-react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { CustomSelect } from '../../components/CustomInputs';
import { useGameServers } from '../../hooks/useGameServers';
import ConfirmDialog from '../../components/feedback/ConfirmDialog';
import NotificationToast from '../../components/feedback/NotificationToast';
import { useConfirmDialog, usePopupToast } from '../../components/feedback/hooks';
import { apiFetch } from '../../api/client';
import { unwrapApiData, getApiErrorMessage } from '../../types/api';
import type { OutletUserContext } from '../../types/auth';
import type {
    PunishmentRemovalCreateInput,
    PunishmentRemovalReason,
    PunishmentRemovalRecord,
    PunishmentRemovalType,
} from '../../types/domain';
import { formatMskToLocal } from '../../utils/datetime';
import { buildGameServerOptions, formatGameServerLabel, getDefaultActiveGameServerId } from '../../utils/gameServers';
import {
    buildRemovalCommand,
    REMOVAL_PUNISHMENT_OPTIONS,
    REMOVAL_REASON_OPTIONS,
    formatRemovalStatusLabel,
    formatRemovalTypeLabel,
    normalizeRemovalReason,
} from './constants';
import { hasPerm } from '../../rbac/guards';

type RemovalsTab = 'queue' | 'history';

type RemovalFormState = {
    punishment_type: PunishmentRemovalType;
    static: string;
    server: string;
    reason: PunishmentRemovalReason;
    message_link: string;
};

type HistoryPayload = {
    items: PunishmentRemovalRecord[];
    total: number;
    page: number;
    pages: number;
};

type HistoryFiltersState = {
    server: string;
};

const createEmptyFormState = (serverId = ''): RemovalFormState => ({
    punishment_type: 'unjail',
    static: '',
    server: serverId,
    reason: 'На видео',
    message_link: '',
});

const emptyHistoryFilters: HistoryFiltersState = {
    server: '',
};

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

function toDatetimeLabel(value?: string | null) {
    return value ? formatMskToLocal(value, { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—';
}

function getStatusTone(status: string) {
    if (status === 'issued' || status === 'completed') return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30';
    if (status === 'pending') return 'bg-amber-500/15 text-amber-300 border-amber-500/30';
    return 'bg-white/10 text-white/70 border-white/10';
}

function CommandBlock({
    value,
    onCopy,
}: {
    value: string;
    onCopy: (value: string) => void;
}) {
    return (
        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
            <div className="flex items-start gap-2">
                <pre className="flex-1 whitespace-pre-wrap break-all text-xs text-white/80 font-mono">{value}</pre>
                <button
                    onClick={() => onCopy(value)}
                    className="p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/50 hover:text-white transition-colors shrink-0"
                    title="Скопировать"
                >
                    <Copy className="w-3.5 h-3.5" />
                </button>
            </div>
        </div>
    );
}

function StatusBadge({ status, label }: { status: string; label: string }) {
    return (
        <span className={`inline-flex px-3 py-1 rounded-full border text-xs font-semibold whitespace-nowrap ${getStatusTone(status)}`}>
            {label || formatRemovalStatusLabel(status)}
        </span>
    );
}

function RemovalFormModal({
    isOpen,
    loading,
    title,
    actorName,
    form,
    existingRecord,
    submittingTarget,
    serverOptions,
    onClose,
    onChange,
    onSubmitDraft,
    onSubmitPending,
    onCopyCommand,
}: {
    isOpen: boolean;
    loading: boolean;
    title: string;
    actorName: string;
    form: RemovalFormState;
    existingRecord: PunishmentRemovalRecord | null;
    submittingTarget: 'draft' | 'pending' | null;
    serverOptions: Array<{ value: string; label: string }>;
    onClose: () => void;
    onChange: (updates: Partial<RemovalFormState>) => void;
    onSubmitDraft: () => void;
    onSubmitPending: () => void;
    onCopyCommand: (value: string) => void;
}) {
    if (!isOpen) return null;

    const previewCommand = buildRemovalCommand(form.punishment_type, form.static, form.reason, actorName);

    return (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-black/60 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]">
            <div className="flex min-h-full items-start justify-center p-3 sm:p-4 lg:items-center">
                <div className="flex w-full max-w-4xl max-h-[calc(100vh-1.5rem)] sm:max-h-[calc(100vh-2rem)] flex-col overflow-hidden rounded-3xl border border-white/10 bg-[#1e1e1e] shadow-2xl">
                <div className="flex items-start justify-between gap-4 px-4 py-4 border-b border-white/5 sm:px-6 sm:py-5">
                    <div>
                        <h3 className="text-xl font-bold text-white sm:text-2xl">{title}</h3>
                        <p className="text-sm text-white/40 mt-1">Черновик виден только автору. Подготовь запись и отправь ее к выдаче, когда будешь готов.</p>
                    </div>
                    <button
                        onClick={onClose}
                        className="px-3 py-2 rounded-xl border border-white/10 text-white/50 hover:text-white hover:bg-white/5 transition-colors"
                    >
                        Закрыть
                    </button>
                </div>

                {loading ? (
                    <div className="p-10 text-center text-white/40">Загрузка записи...</div>
                ) : (
                    <div className="min-h-0 overflow-y-auto">
                    <div className="grid grid-cols-1 xl:grid-cols-[1.1fr_0.9fr]">
                        <div className="p-4 sm:p-6 border-b border-white/5 space-y-5 xl:border-b-0 xl:border-r">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label className="text-xs font-medium text-white/40 mb-1 block">PR Assistant</label>
                                    <input
                                        type="text"
                                        value={actorName}
                                        readOnly
                                        className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2.5 px-3 text-sm text-white/80 outline-none"
                                    />
                                </div>
                                <div>
                                    <label className="text-xs font-medium text-white/40 mb-1 block">Наказание</label>
                                    <CustomSelect
                                        value={form.punishment_type}
                                        onChange={(value) => {
                                            if (typeof value === 'string') {
                                                onChange({ punishment_type: value as PunishmentRemovalType });
                                            }
                                        }}
                                        options={REMOVAL_PUNISHMENT_OPTIONS.map((item) => ({ value: item.value, label: item.label }))}
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
                                        className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2.5 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                        placeholder="Например, 138254"
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
                                        options={serverOptions}
                                    />
                                </div>
                            </div>

                            <div>
                                <label className="text-xs font-medium text-white/40 mb-1 block">Причина</label>
                                <CustomSelect
                                    value={form.reason}
                                    onChange={(value) => {
                                        if (typeof value === 'string') {
                                            onChange({ reason: value as PunishmentRemovalReason });
                                        }
                                    }}
                                    options={REMOVAL_REASON_OPTIONS.map((item) => ({ value: item.value, label: item.label }))}
                                />
                            </div>

                            <div>
                                <label className="text-xs font-medium text-white/40 mb-1 block">Ссылка на сообщение</label>
                                <input
                                    type="url"
                                    value={form.message_link}
                                    onChange={(e) => onChange({ message_link: e.target.value })}
                                    className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2.5 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                    placeholder="https://discord.com/channels/..."
                                />
                            </div>
                        </div>

                        <div className="p-4 sm:p-6 bg-white/[0.02] space-y-4">
                            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 space-y-3">
                                <div>
                                    <div className="text-xs uppercase tracking-wide text-white/30 mb-1">PR Assistant</div>
                                    <div className="text-white font-semibold">{actorName}</div>
                                </div>
                                <div>
                                    <div className="text-xs uppercase tracking-wide text-white/30 mb-1">Сервер</div>
                                    <div className="text-white/80">
                                        {serverOptions.find((option) => option.value === form.server)?.label || formatGameServerLabel(form.server, 'full')}
                                    </div>
                                </div>
                                <div>
                                    <div className="text-xs uppercase tracking-wide text-white/30 mb-1">Статус</div>
                                    <div className="text-white/80">{existingRecord?.status_label || 'Черновик'}</div>
                                </div>
                                <div>
                                    <div className="text-xs uppercase tracking-wide text-white/30 mb-1">Дата</div>
                                    <div className="text-white/80">{existingRecord ? toDatetimeLabel(existingRecord.created_at || existingRecord.reviewed_at || existingRecord.issued_at) : '—'}</div>
                                </div>
                                <div>
                                    <div className="text-xs uppercase tracking-wide text-white/30 mb-1">Причина</div>
                                    <div className="text-white/80 break-words">{form.reason.trim() || '—'}</div>
                                </div>
                            </div>

                            <div className="space-y-3">
                                <div className="rounded-2xl border border-white/10 bg-black/20 p-4 space-y-3">
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="text-xs uppercase tracking-wide text-white/30">Команда</div>
                                        <button
                                            type="button"
                                            onClick={() => onCopyCommand(previewCommand)}
                                            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/60 hover:text-white transition-colors text-xs"
                                        >
                                            <Copy className="w-3.5 h-3.5" />
                                            Скопировать
                                        </button>
                                    </div>
                                    <pre className="whitespace-pre-wrap break-all text-sm text-blue-300 font-mono">{previewCommand}</pre>
                                </div>
                            </div>

                            <div className="flex flex-col gap-3 pt-2">
                                <button
                                    onClick={onSubmitDraft}
                                    disabled={submittingTarget !== null}
                                    className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white/80 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-50"
                                >
                                    {submittingTarget === 'draft' ? 'Сохранение...' : 'Сохранить как черновик'}
                                </button>
                                <button
                                    onClick={onSubmitPending}
                                    disabled={submittingTarget !== null}
                                    className="w-full px-4 py-3 rounded-xl bg-blue-500/15 border border-blue-500/30 text-blue-300 font-semibold hover:bg-blue-500/25 transition-colors disabled:opacity-50"
                                >
                                    {submittingTarget === 'pending' ? 'Отправка...' : 'Отправить к выдаче'}
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
                )}
            </div>
            </div>
        </div>
    );
}

export default function PunishmentRemovals() {
    const { user } = useOutletContext<OutletUserContext>();
    const navigate = useNavigate();
    const { toast, showToast, closeToast } = usePopupToast(2400);
    const { confirm, dialogProps } = useConfirmDialog();
    const { servers: gameServers, serversById } = useGameServers();

    const canViewQueue = hasPerm(user, 'removals.queue.view');
    const canViewHistory = hasPerm(user, 'removals.history.view');
    const canCreate = hasPerm(user, 'removals.create');

    const [activeTab, setActiveTab] = React.useState<RemovalsTab>(() => (canViewQueue ? 'queue' : 'history'));
    const [queueItems, setQueueItems] = React.useState<PunishmentRemovalRecord[]>([]);
    const [historyItems, setHistoryItems] = React.useState<PunishmentRemovalRecord[]>([]);
    const [queueLoading, setQueueLoading] = React.useState(true);
    const [historyLoading, setHistoryLoading] = React.useState(false);
    const [historyPage, setHistoryPage] = React.useState(1);
    const [historyTotalPages, setHistoryTotalPages] = React.useState(1);
    const [historyTotal, setHistoryTotal] = React.useState(0);
    const [historyFilters, setHistoryFilters] = React.useState<HistoryFiltersState>(emptyHistoryFilters);
    const [editorOpen, setEditorOpen] = React.useState(false);
    const [editorMode, setEditorMode] = React.useState<'create' | 'edit'>('create');
    const [editorLoading, setEditorLoading] = React.useState(false);
    const [editingRecord, setEditingRecord] = React.useState<PunishmentRemovalRecord | null>(null);
    const [formState, setFormState] = React.useState<RemovalFormState>(() => createEmptyFormState());
    const [submittingTarget, setSubmittingTarget] = React.useState<'draft' | 'pending' | null>(null);
    const [deletingId, setDeletingId] = React.useState<string | null>(null);

    const actorName = user?.nickname || 'unknown';
    const historyPageRef = React.useRef(historyPage);
    const historyFiltersRef = React.useRef(historyFilters);

    React.useEffect(() => {
        historyPageRef.current = historyPage;
    }, [historyPage]);

    React.useEffect(() => {
        historyFiltersRef.current = historyFilters;
    }, [historyFilters]);

    const defaultServerId = React.useMemo(() => getDefaultActiveGameServerId(gameServers), [gameServers]);
    const createFormState = React.useCallback((serverId = defaultServerId) => createEmptyFormState(serverId), [defaultServerId]);

    React.useEffect(() => {
        if (activeTab === 'queue' && !canViewQueue && canViewHistory) {
            setActiveTab('history');
            return;
        }
        if (activeTab === 'history' && !canViewHistory && canViewQueue) {
            setActiveTab('queue');
        }
    }, [activeTab, canViewHistory, canViewQueue]);

    const normalizeForm = React.useCallback((record?: PunishmentRemovalRecord | null): RemovalFormState => {
        if (!record) return createFormState();
        return {
            punishment_type: record.punishment_type,
            static: String(record.static || ''),
            server: String(record.server),
            reason: normalizeRemovalReason(record.reason),
            message_link: record.message_link || '',
        };
    }, [createFormState]);

    const fetchQueue = React.useCallback(async () => {
        setQueueLoading(true);
        try {
            const response = await apiFetch('/api/removals/queue');
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payload, 'Не удалось загрузить очередь снятий'));
            }
            const json = await response.json() as unknown;
            const data = unwrapApiData<unknown>(json);
            const items = Array.isArray(data)
                ? data
                : Array.isArray((data as { items?: PunishmentRemovalRecord[] } | null)?.items)
                    ? (data as { items: PunishmentRemovalRecord[] }).items
                    : [];
            setQueueItems(items as PunishmentRemovalRecord[]);
        } catch (error) {
            console.error('Failed to fetch removals queue:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось загрузить очередь снятий', 'error');
        } finally {
            setQueueLoading(false);
        }
    }, [showToast]);

    const fetchHistory = React.useCallback(async (page = 1, filtersOverride?: HistoryFiltersState) => {
        setHistoryLoading(true);
        try {
            const activeFilters = filtersOverride ?? historyFiltersRef.current;
            const params = new URLSearchParams({ page: String(page), limit: '20' });
            if (activeFilters.server) params.append('server', activeFilters.server);
            const response = await apiFetch(`/api/removals/history?${params.toString()}`);
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payload, 'Не удалось загрузить историю снятий'));
            }
            const json = await response.json() as unknown;
            const data = unwrapApiData<unknown>(json);
            const normalized = (Array.isArray(data) ? { items: data } : data) as Partial<HistoryPayload>;
            setHistoryItems((normalized.items || []) as PunishmentRemovalRecord[]);
            setHistoryTotal(normalized.total || 0);
            setHistoryPage(normalized.page || 1);
            setHistoryTotalPages(normalized.pages || 1);
        } catch (error) {
            console.error('Failed to fetch removals history:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось загрузить историю снятий', 'error');
        } finally {
            setHistoryLoading(false);
        }
    }, [showToast]);

    React.useEffect(() => {
        if (activeTab === 'queue' && canViewQueue) {
            void fetchQueue();
            const interval = window.setInterval(() => void fetchQueue(), 15000);
            return () => window.clearInterval(interval);
        }
        if (activeTab === 'history' && canViewHistory) {
            void fetchHistory(1);
        }
        return undefined;
    }, [activeTab, canViewHistory, canViewQueue, fetchHistory, fetchQueue]);

    const closeEditor = React.useCallback(() => {
        setEditorOpen(false);
        setEditorMode('create');
        setEditorLoading(false);
        setEditingRecord(null);
        setFormState(createFormState());
        setSubmittingTarget(null);
    }, [createFormState]);

    const openCreate = React.useCallback(() => {
        setEditorMode('create');
        setEditingRecord(null);
        setFormState(createFormState());
        setEditorOpen(true);
    }, [createFormState]);

    const openEdit = React.useCallback((record: PunishmentRemovalRecord) => {
        setEditorMode('edit');
        setEditingRecord(record);
        setFormState(normalizeForm(record));
        setEditorOpen(true);
    }, [normalizeForm]);

    const copyCommand = React.useCallback(async (value: string) => {
        try {
            await navigator.clipboard.writeText(value);
            showToast('Скопировано');
        } catch {
            showToast('Не удалось скопировать', 'error');
        }
    }, [showToast]);

    const serializePayload = React.useCallback((
        targetStatus: 'draft' | 'pending',
        form: RemovalFormState,
        allowedInactiveServerId: number | null = null,
    ) => {
        const server = Number(form.server);
        const staticValue = Number(form.static);
        const selectedServer = Number.isInteger(server) ? serversById[server] : undefined;

        if (!Number.isInteger(server) || server < 1 || !selectedServer || (!selectedServer.is_active && allowedInactiveServerId !== server)) {
            showToast('Выберите сервер', 'error');
            return null;
        }
        if (!Number.isInteger(staticValue) || staticValue <= 0) {
            showToast('Заполните статик', 'error');
            return null;
        }
        return {
            punishment_type: form.punishment_type,
            static: staticValue,
            server,
            reason: form.reason,
            message_link: form.message_link.trim() || null,
            target_status: targetStatus,
        } satisfies PunishmentRemovalCreateInput;
    }, [serversById, showToast]);

    const submitRemoval = React.useCallback(async (targetStatus: 'draft' | 'pending') => {
        const payload = serializePayload(targetStatus, formState, editorMode === 'edit' ? editingRecord?.server ?? null : null);
        if (!payload) return;

        setSubmittingTarget(targetStatus);
        try {
            const response = await apiFetch(
                editorMode === 'edit' && editingRecord ? `/api/removals/${editingRecord.id}` : '/api/removals',
                {
                    method: editorMode === 'edit' && editingRecord ? 'PATCH' : 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                },
            );
            if (!response.ok) {
                const payloadError = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payloadError, 'Не удалось сохранить запись'));
            }

            showToast(targetStatus === 'draft' ? 'Черновик сохранен' : 'Запись отправлена к выдаче');
            closeEditor();
            if (canViewQueue) {
                await fetchQueue();
            }
            if (canViewHistory) {
                await fetchHistory(historyPageRef.current);
            }
        } catch (error) {
            console.error('Failed to submit removal:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось сохранить запись', 'error');
        } finally {
            setSubmittingTarget(null);
        }
    }, [canViewHistory, canViewQueue, closeEditor, editorMode, editingRecord, fetchHistory, fetchQueue, formState, historyPageRef, serializePayload, showToast]);

    const submitRemovalRecord = React.useCallback(async (record: PunishmentRemovalRecord) => {
        const payload = serializePayload('pending', normalizeForm(record), record.server);
        if (!payload) return;

        try {
            const response = await apiFetch(`/api/removals/${record.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!response.ok) {
                const payloadError = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payloadError, 'Не удалось отправить запись к выдаче'));
            }

            showToast('Запись отправлена к выдаче');
            if (canViewQueue) {
                await fetchQueue();
            }
            if (canViewHistory) {
                await fetchHistory(historyPageRef.current);
            }
        } catch (error) {
            console.error('Failed to submit removal record:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось отправить запись к выдаче', 'error');
        }
    }, [canViewHistory, canViewQueue, fetchHistory, fetchQueue, historyPageRef, normalizeForm, serializePayload, showToast]);

    const issueRemoval = React.useCallback(async (record: PunishmentRemovalRecord) => {
        try {
            const response = await apiFetch(`/api/removals/${record.id}/issue`, {
                method: 'POST',
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payload, 'Не удалось выдать запись'));
            }
            showToast('Запись выдана');
            await fetchQueue();
            if (canViewHistory) {
                await fetchHistory(1);
            }
        } catch (error) {
            console.error('Failed to issue removal:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось выдать запись', 'error');
        }
    }, [canViewHistory, fetchHistory, fetchQueue, showToast]);

    const deleteRemoval = React.useCallback(async (record: PunishmentRemovalRecord) => {
        const confirmed = await confirm({
            title: 'Удалить запись?',
            message: (
                <>
                    Запись для статика <span className="text-white font-semibold">{record.static}</span> будет удалена.
                </>
            ),
            tone: 'danger',
            confirmLabel: 'Удалить',
        });

        if (!confirmed) return;

        setDeletingId(record.id);
        try {
            const response = await apiFetch(`/api/removals/${record.id}`, {
                method: 'DELETE',
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payload, 'Не удалось удалить запись'));
            }
            showToast('Запись удалена');
            if (canViewQueue) {
                await fetchQueue();
            }
            if (canViewHistory) {
                await fetchHistory(historyPageRef.current);
            }
        } catch (error) {
            console.error('Failed to delete removal:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось удалить запись', 'error');
        } finally {
            setDeletingId(null);
        }
    }, [canViewHistory, canViewQueue, confirm, fetchHistory, fetchQueue, historyPageRef, showToast]);

    const renderQueueActions = (item: PunishmentRemovalRecord, primary: boolean) => {
        const buttons: React.ReactNode[] = [];

        if (primary && item.status === 'draft' && item.can_submit) {
            buttons.push(
                <button
                    key="submit"
                    onClick={() => void submitRemovalRecord(item)}
                    className="px-3 py-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 transition-colors text-xs font-semibold whitespace-nowrap"
                >
                    Отправить к выдаче
                </button>,
            );
        }

        if (primary && item.status === 'pending' && item.can_issue) {
            buttons.push(
                <button
                    key="issue"
                    onClick={() => void issueRemoval(item)}
                    className="px-3 py-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 transition-colors text-xs font-semibold whitespace-nowrap"
                >
                    Выдать
                </button>,
            );
        }

        if (primary && item.can_edit) {
            buttons.push(
                <button
                    key="edit"
                    onClick={() => openEdit(item)}
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
                    onClick={() => void deleteRemoval(item)}
                    disabled={deletingId === item.id}
                    className="p-2 rounded-lg border border-red-500/20 bg-red-500/10 text-red-300 hover:bg-red-500/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    title="Удалить"
                >
                    <Trash2 className="w-3.5 h-3.5" />
                </button>,
            );
        }

        return <div className="flex flex-nowrap items-center gap-2 justify-end min-w-max">{buttons}</div>;
    };

    const serverOptions = React.useMemo(() => buildGameServerOptions(gameServers, {
        variant: 'full',
        includeInactive: editorMode === 'edit',
        selectedServerId: formState.server,
    }), [editorMode, formState.server, gameServers]);

    const historyServerOptions = React.useMemo(() => buildGameServerOptions(gameServers, {
        variant: 'full',
        includeInactive: true,
        includeEmptyOptionLabel: 'Все серверы',
        selectedServerId: historyFilters.server,
    }), [gameServers, historyFilters.server]);

    const primaryRows = new Set<string>();

    return (
        <div className="space-y-6 animate-[fadeIn_0.5s_ease-in-out] -mx-[calc(50vw-50%)] px-6 lg:px-12 pr-10 lg:pr-16">
            <div className="flex items-center justify-between gap-4">
                <h2 className="text-3xl font-bold flex items-center gap-2">
                    <span className="w-1 h-8 bg-[#fb7185] rounded-full inline-block" />
                    Снятие наказаний
                </h2>
                {canCreate && (
                    <button
                        onClick={openCreate}
                        className="inline-flex items-center gap-2 px-4 py-3 rounded-xl border border-blue-500/20 bg-blue-500/10 text-blue-300 font-semibold hover:bg-blue-500/20 transition-colors"
                    >
                        <Plus className="w-4 h-4" />
                        Создать снятие
                    </button>
                )}
            </div>

            <div className="flex gap-2 border-b border-white/10 pb-2">
                {canViewQueue && (
                    <button
                        onClick={() => setActiveTab('queue')}
                        className={`px-6 py-3 rounded-t-lg font-semibold transition-all ${activeTab === 'queue'
                            ? 'bg-white/10 text-white border-b-2 border-blue-500'
                            : 'text-white/60 hover:text-white hover:bg-white/5'
                            }`}
                    >
                        К выдаче
                    </button>
                )}
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

            {activeTab === 'queue' && canViewQueue && (
                <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden">
                    {queueLoading ? (
                        <div className="p-10 text-center text-white/40">Загрузка очереди...</div>
                    ) : queueItems.length === 0 ? (
                        <div className="p-10 text-center text-white/40">Нет активных снятий</div>
                    ) : (
                        <div className="overflow-visible">
                            <table className="w-full text-left border-collapse">
                                <thead className="bg-[#1a1a1a]/80 border-b border-white/5 text-xs text-white/40 font-bold uppercase tracking-wider">
                                    <tr>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">СТАТИК / СЕРВЕР</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">НАКАЗАНИЕ</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">PR ASSISTANT</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">ПРИЧИНА</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">ДАТА</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">СТАТУС</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">ССЫЛКА</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">КОМАНДА</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap text-right">ДЕЙСТВИЕ</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-white/5">
                                    {queueItems.map((item) => {
                                        const primary = !primaryRows.has(item.id);
                                        primaryRows.add(item.id);

                                        return (
                                            <tr key={item.id} className="hover:bg-white/5 transition-colors align-top">
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="font-bold text-white/90">{item.static}</div>
                                                    <div className="text-xs text-white/40 mt-1">{formatGameServerLabel(item.server, 'full', serversById)}</div>
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="font-bold text-white/90">{formatRemovalTypeLabel(item.punishment_type)}</div>
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    {item.assistant_id ? (
                                                        <button
                                                            type="button"
                                                            onClick={() => navigate(`/assistants/${item.assistant_id}`)}
                                                            className="font-semibold text-white/80 hover:text-white underline decoration-white/20 underline-offset-2 transition-colors"
                                                        >
                                                            {item.assistant_name}
                                                        </button>
                                                    ) : (
                                                        <div className="font-semibold text-white/80">{item.assistant_name || '—'}</div>
                                                    )}
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="max-w-[260px] text-xs text-white/70 break-words whitespace-pre-wrap">{item.reason}</div>
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="text-sm text-white/70">{toDatetimeLabel(item.created_at || item.reviewed_at || item.issued_at)}</div>
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <StatusBadge status={item.status} label={item.status_label} />
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    {item.message_link ? (
                                                        <a
                                                            href={item.message_link}
                                                            target="_blank"
                                                            rel="noreferrer"
                                                            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white/70 hover:text-white hover:bg-white/10 transition-colors text-xs font-semibold whitespace-nowrap"
                                                        >
                                                            Открыть
                                                            <ExternalLink className="w-3.5 h-3.5" />
                                                        </a>
                                                    ) : (
                                                        <span className="inline-flex px-3 py-2 rounded-lg border border-white/10 bg-white/[0.03] text-white/35 text-xs font-semibold whitespace-nowrap">—</span>
                                                    )}
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <CommandBlock value={item.command} onCopy={(value) => void copyCommand(value)} />
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap text-right">
                                                    {renderQueueActions(item, primary)}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'history' && canViewHistory && (
                <div className="space-y-4">
                    <div className="relative z-50 bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-4 flex flex-wrap gap-4 items-end overflow-visible">
                        <div className="w-[220px]">
                            <label className="text-xs font-medium text-white/40 mb-1 block">Сервер</label>
                            <CustomSelect
                                value={historyFilters.server}
                                onChange={(value) => {
                                    if (typeof value === 'string') {
                                        setHistoryFilters((prev) => ({ ...prev, server: value }));
                                    }
                                }}
                                options={historyServerOptions}
                            />
                        </div>

                        <div className="flex gap-2">
                            <button
                                onClick={() => {
                                    setHistoryPage(1);
                                    void fetchHistory(1, historyFilters);
                                }}
                                className="px-4 py-2 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 border border-blue-500/20 rounded-lg text-sm font-medium transition-colors"
                            >
                                Применить
                            </button>
                            <button
                                onClick={() => {
                                    setHistoryFilters(emptyHistoryFilters);
                                    setHistoryPage(1);
                                    void fetchHistory(1, emptyHistoryFilters);
                                }}
                                className="px-4 py-2 bg-white/5 hover:bg-white/10 text-white/60 hover:text-white border border-white/5 rounded-lg text-sm font-medium transition-colors"
                            >
                                Сброс
                            </button>
                        </div>
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
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">PR ASSISTANT</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">ПРИЧИНА</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">ДАТА</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">СТАТУС</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">ССЫЛКА</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">КОМАНДА</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap text-right">ДЕЙСТВИЕ</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-white/5">
                                        {historyItems.map((item) => {
                                            const primary = !primaryRows.has(`history-${item.id}`);
                                            primaryRows.add(`history-${item.id}`);

                                            return (
                                                <tr key={item.id} className="hover:bg-white/5 transition-colors align-top">
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="font-bold text-white/90">{item.static}</div>
                                                    <div className="text-xs text-white/40 mt-1">{formatGameServerLabel(item.server, 'full', serversById)}</div>
                                                </td>
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        <div className="font-bold text-white/90">{formatRemovalTypeLabel(item.punishment_type)}</div>
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        {item.assistant_id ? (
                                                            <button
                                                                type="button"
                                                                onClick={() => navigate(`/assistants/${item.assistant_id}`)}
                                                                className="font-semibold text-white/80 hover:text-white underline decoration-white/20 underline-offset-2 transition-colors"
                                                            >
                                                                {item.assistant_name}
                                                            </button>
                                                        ) : (
                                                            <div className="font-semibold text-white/80">{item.assistant_name || '—'}</div>
                                                        )}
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        <div className="max-w-[260px] text-xs text-white/70 break-words whitespace-pre-wrap">{item.reason}</div>
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        <div className="text-sm text-white/70">{toDatetimeLabel(item.created_at || item.reviewed_at || item.issued_at)}</div>
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        <StatusBadge status={item.status} label={item.status_label} />
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        {item.message_link ? (
                                                            <a
                                                                href={item.message_link}
                                                                target="_blank"
                                                                rel="noreferrer"
                                                                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white/70 hover:text-white hover:bg-white/10 transition-colors text-xs font-semibold whitespace-nowrap"
                                                            >
                                                                Открыть
                                                                <ExternalLink className="w-3.5 h-3.5" />
                                                            </a>
                                                        ) : (
                                                            <span className="inline-flex px-3 py-2 rounded-lg border border-white/10 bg-white/[0.03] text-white/35 text-xs font-semibold whitespace-nowrap">—</span>
                                                        )}
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        <CommandBlock value={item.command} onCopy={(value) => void copyCommand(value)} />
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap text-right">
                                                        {renderQueueActions(item, primary)}
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>

                    {historyTotalPages > 1 && (
                        <div className="flex items-center justify-between gap-4 flex-wrap">
                            <div className="text-sm text-white/50">
                                Всего записей: <span className="text-white/80 font-semibold">{historyTotal}</span>
                            </div>
                            <div className="flex items-center gap-2 flex-wrap">
                                <button
                                    onClick={() => void fetchHistory(historyPage - 1)}
                                    disabled={historyPage <= 1}
                                    className="px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white/70 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                >
                                    <ChevronLeft className="w-4 h-4" />
                                </button>
                                {getPageNumbers(historyTotalPages, historyPage).map((page, index) => (
                                    page === '...'
                                        ? <span key={`ellipsis-${index}`} className="px-2 text-white/30">...</span>
                                        : (
                                            <button
                                                key={page}
                                                onClick={() => void fetchHistory(page)}
                                                className={`min-w-10 px-3 py-2 rounded-lg border text-sm font-medium transition-colors ${page === historyPage
                                                    ? 'border-blue-500/40 bg-blue-500/15 text-blue-300'
                                                    : 'border-white/10 bg-white/5 text-white/70 hover:text-white hover:bg-white/10'
                                                    }`}
                                            >
                                                {page}
                                            </button>
                                        )
                                ))}
                                <button
                                    onClick={() => void fetchHistory(historyPage + 1)}
                                    disabled={historyPage >= historyTotalPages}
                                    className="px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white/70 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                >
                                    <ChevronRight className="w-4 h-4" />
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            )}

            <RemovalFormModal
                isOpen={editorOpen}
                loading={editorLoading}
                title={editorMode === 'edit' ? 'Редактирование снятия' : 'Создание снятия'}
                actorName={actorName}
                form={formState}
                existingRecord={editingRecord}
                submittingTarget={submittingTarget}
                serverOptions={serverOptions}
                onClose={closeEditor}
                onChange={(updates) => setFormState((prev) => ({ ...prev, ...updates }))}
                onSubmitDraft={() => void submitRemoval('draft')}
                onSubmitPending={() => void submitRemoval('pending')}
                onCopyCommand={(value) => void copyCommand(value)}
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
