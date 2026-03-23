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
    ComplaintCreateInput,
    ComplaintDetail,
    ComplaintListItem,
    ComplaintPunishmentItem,
    ComplaintPunishmentType,
    ComplaintSummary,
    ComplaintUpdateInput,
} from '../../types/domain';
import { formatMskToLocal } from '../../utils/datetime';
import { buildGameServerOptions, formatGameServerLabel, getDefaultActiveGameServerId } from '../../utils/gameServers';
import {
    buildComplaintCommandsPreview,
    buildComplaintMessagesPreview,
    COMPLAINT_PUNISHMENT_OPTIONS,
    formatComplaintDurationLabel,
    formatComplaintPunishmentLabel,
    formatComplaintStatusLabel,
} from './constants';
import { hasPerm } from '../../rbac/guards';

type ComplaintsTab = 'queue' | 'history';

type ComplaintPunishmentFormState = {
    punishment_type: ComplaintPunishmentType;
    static: string;
    duration: string;
    reason: string;
};

type ComplaintFormState = {
    server: string;
    media: string;
    complaint_link: string;
    incident_at: string;
    punishments: ComplaintPunishmentFormState[];
};

type HistoryFiltersState = {
    server: string;
};

type HistoryPayload = {
    items: ComplaintListItem[];
    total: number;
    page: number;
    pages: number;
};

const emptyPunishment = (): ComplaintPunishmentFormState => ({
    punishment_type: 'mute',
    static: '',
    duration: '',
    reason: '',
});

const createEmptyFormState = (serverId = ''): ComplaintFormState => ({
    server: serverId,
    media: '',
    complaint_link: '',
    incident_at: '',
    punishments: [emptyPunishment()],
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

function toDatetimeLocalValue(value?: string | null): string {
    if (!value) return '';
    return value.length >= 16 ? value.slice(0, 16) : value;
}

function getComplaintStatusTone(status: string) {
    if (status === 'issued' || status === 'completed') {
        return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30';
    }
    if (status === 'pending') {
        return 'bg-amber-500/15 text-amber-300 border-amber-500/30';
    }
    return 'bg-white/10 text-white/70 border-white/10';
}

function getComplaintDisplayDate(item: Pick<ComplaintSummary, 'status' | 'issued_at' | 'reviewed_at' | 'created_at'>): string {
    const source = item.status === 'issued' || item.status === 'completed'
        ? (item.issued_at || item.reviewed_at || item.created_at)
        : item.status === 'pending'
            ? (item.reviewed_at || item.created_at)
            : item.created_at;
    return source ? formatMskToLocal(source, { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—';
}

function getComplaintPreviewActorName(item: Pick<ComplaintSummary, 'status' | 'assistant_name' | 'issued_by_name'>): string {
    if (item.status === 'issued' || item.status === 'completed') {
        return item.issued_by_name || item.assistant_name || 'unknown';
    }
    return item.assistant_name || 'unknown';
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
                        <pre className="flex-1 whitespace-pre-wrap break-all text-xs text-white/80 font-mono">{line.value}</pre>
                        <button
                            onClick={() => onCopy(line.value)}
                            className="p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/50 hover:text-white transition-colors shrink-0"
                            title="Скопировать"
                        >
                            <Copy className="w-3.5 h-3.5" />
                        </button>
                    </div>
                </div>
            ))}
        </div>
    );
}

function ComplaintStatusBadge({ status, label }: { status: string; label: string }) {
    return (
        <span className={`inline-flex px-3 py-1 rounded-full border text-xs font-semibold whitespace-nowrap ${getComplaintStatusTone(status)}`}>
            {label || formatComplaintStatusLabel(status)}
        </span>
    );
}

function ComplaintFormModal({
    isOpen,
    loading,
    title,
    actorName,
    form,
    existingComplaint,
    submittingTarget,
    serverOptions,
    onClose,
    onChange,
    onAddPunishment,
    onRequestRemovePunishment,
    onSubmitDraft,
    onSubmitPending,
    onSubmitIssuedSave,
    onCopyCommand,
}: {
    isOpen: boolean;
    loading: boolean;
    title: string;
    actorName: string;
    form: ComplaintFormState;
    existingComplaint: ComplaintDetail['complaint'] | null;
    submittingTarget: 'draft' | 'pending' | 'save' | null;
    serverOptions: Array<{ value: string; label: string }>;
    onClose: () => void;
    onChange: (updates: Partial<ComplaintFormState>) => void;
    onAddPunishment: () => void;
    onRequestRemovePunishment: (index: number) => void;
    onSubmitDraft: () => void;
    onSubmitPending: () => void;
    onSubmitIssuedSave: () => void;
    onCopyCommand: (value: string) => void;
}) {
    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-black/60 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]">
            <div className="flex min-h-full items-start justify-center p-3 sm:p-4 lg:items-center">
                <div className="flex w-full max-w-6xl max-h-[calc(100vh-1.5rem)] sm:max-h-[calc(100vh-2rem)] flex-col overflow-hidden rounded-3xl border border-white/10 bg-[#1e1e1e] shadow-2xl">
                    <div className="flex items-center justify-between gap-4 px-4 py-4 border-b border-white/5 sm:px-6 sm:py-5">
                        <div>
                            <div className="text-xs uppercase tracking-wide text-white/30 mb-1">{title}</div>
                            {existingComplaint && (
                                <div className="text-sm text-white/50">
                                    Жалоба #{existingComplaint.id}
                                </div>
                            )}
                        </div>
                        <button
                            onClick={onClose}
                            className="px-3 py-2 rounded-xl border border-white/10 text-white/50 hover:text-white hover:bg-white/5 transition-colors"
                        >
                            Закрыть
                        </button>
                    </div>

                    {loading ? (
                        <div className="p-10 text-center text-white/40">Загрузка жалобы...</div>
                    ) : (
                        <div className="min-h-0 overflow-y-auto">
                            <div className="grid grid-cols-1 xl:grid-cols-[1.15fr_0.85fr]">
                                <div className="p-4 sm:p-6 border-b border-white/5 space-y-6 xl:border-b-0 xl:border-r">
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
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
                                        <div>
                                            <label className="text-xs font-medium text-white/40 mb-1 block">Медиа</label>
                                            <input
                                                type="text"
                                                value={form.media}
                                                onChange={(e) => onChange({ media: e.target.value })}
                                                aria-label="Медиа"
                                                className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2.5 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                                placeholder="Ник"
                                            />
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        <div>
                                            <label className="text-xs font-medium text-white/40 mb-1 block">Дата и время нарушения</label>
                                            <input
                                                type="datetime-local"
                                                value={form.incident_at}
                                                onChange={(e) => onChange({ incident_at: e.target.value })}
                                                aria-label="Дата и время нарушения"
                                                className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2.5 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-xs font-medium text-white/40 mb-1 block">Ссылка на жалобу</label>
                                            <input
                                                type="url"
                                                value={form.complaint_link}
                                                onChange={(e) => onChange({ complaint_link: e.target.value })}
                                                className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2.5 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                                placeholder="https://..."
                                            />
                                        </div>
                                    </div>

                                    <div className="space-y-4">
                                        <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
                                            <div>
                                                <h4 className="text-lg font-semibold text-white">Наказания</h4>
                                                <p className="text-xs text-white/40">Минимум одно наказание на жалобу.</p>
                                            </div>
                                            <button
                                                type="button"
                                                onClick={onAddPunishment}
                                                className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-sm font-semibold text-blue-300 transition-colors hover:bg-blue-500/20 sm:w-auto"
                                            >
                                                <Plus className="w-4 h-4" />
                                                Добавить наказание
                                            </button>
                                        </div>

                                        <div className="space-y-3">
                                            <div className="hidden rounded-xl border border-white/10 bg-black/20 px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-white/35 lg:grid lg:grid-cols-[1.05fr_0.72fr_0.72fr_1.4fr_auto] lg:gap-3">
                                                <span>Тип</span>
                                                <span>Статик</span>
                                                <span>Срок</span>
                                                <span>Причина</span>
                                                <span className="text-right">Действие</span>
                                            </div>
                                            {form.punishments.map((punishment, index) => {
                                                return (
                                                    <div
                                                        key={`${punishment.punishment_type}-${index}`}
                                                        className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3"
                                                    >
                                                        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-white/35 lg:hidden">
                                                            Наказание #{index + 1}
                                                        </div>
                                                        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1.05fr_0.72fr_0.72fr_1.4fr_auto] lg:items-end">
                                                            <div className="min-w-0">
                                                                <label className="text-xs font-medium text-white/40 mb-1 block lg:hidden">Тип</label>
                                                                <CustomSelect
                                                                    value={punishment.punishment_type}
                                                                    onChange={(value) => {
                                                                        if (typeof value !== 'string') return;
                                                                        const nextValue = value as ComplaintPunishmentType;
                                                                        onChange({
                                                                            punishments: form.punishments.map((item, itemIndex) => (
                                                                                itemIndex === index
                                                                                    ? {
                                                                                        ...item,
                                                                                        punishment_type: nextValue,
                                                                                        duration: nextValue === 'warn' ? '' : item.duration,
                                                                                    }
                                                                                    : item
                                                                            )),
                                                                        });
                                                                    }}
                                                                    options={COMPLAINT_PUNISHMENT_OPTIONS.map((item) => ({ value: item.value, label: item.label }))}
                                                                />
                                                            </div>

                                                            <div>
                                                                <label className="text-xs font-medium text-white/40 mb-1 block lg:hidden">Статик</label>
                                                                <input
                                                                    type="number"
                                                                    min="1"
                                                                    value={punishment.static}
                                                                    onChange={(e) => {
                                                                        onChange({
                                                                            punishments: form.punishments.map((item, itemIndex) => (
                                                                                itemIndex === index
                                                                                    ? { ...item, static: e.target.value }
                                                                                    : item
                                                                            )),
                                                                        });
                                                                    }}
                                                                    className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2.5 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                                                    placeholder="Static"
                                                                />
                                                            </div>

                                                            <div>
                                                                <label className="text-xs font-medium text-white/40 mb-1 block lg:hidden">Срок</label>
                                                                {punishment.punishment_type !== 'warn' ? (
                                                                    <input
                                                                        type="number"
                                                                        min="1"
                                                                        value={punishment.duration}
                                                                        onChange={(e) => {
                                                                            onChange({
                                                                                punishments: form.punishments.map((item, itemIndex) => (
                                                                                    itemIndex === index
                                                                                        ? { ...item, duration: e.target.value }
                                                                                        : item
                                                                                )),
                                                                            });
                                                                        }}
                                                                        className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2.5 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                                                        placeholder="30"
                                                                    />
                                                                ) : (
                                                                    <div className="inline-flex h-[42px] w-full items-center rounded-lg border border-white/10 bg-black/20 px-3 text-sm text-white/50">
                                                                        Без срока
                                                                    </div>
                                                                )}
                                                            </div>

                                                            <div className="min-w-0">
                                                                <label className="text-xs font-medium text-white/40 mb-1 block lg:hidden">Причина</label>
                                                                <input
                                                                    type="text"
                                                                    value={punishment.reason}
                                                                    onChange={(e) => {
                                                                        onChange({
                                                                            punishments: form.punishments.map((item, itemIndex) => (
                                                                                itemIndex === index
                                                                                    ? { ...item, reason: e.target.value }
                                                                                    : item
                                                                            )),
                                                                        });
                                                                    }}
                                                                    className="w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2.5 px-3 text-sm text-white outline-none focus:border-blue-500/40"
                                                                    placeholder="Причина наказания"
                                                                />
                                                            </div>

                                                            <div className="flex lg:justify-end">
                                                                <button
                                                                    type="button"
                                                                    onClick={() => onRequestRemovePunishment(index)}
                                                                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-300 transition-colors hover:bg-red-500/20 lg:w-auto"
                                                                    title="Удалить наказание"
                                                                >
                                                                    <Trash2 className="w-3.5 h-3.5" />
                                                                    Удалить
                                                                </button>
                                                            </div>
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
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
                                            <div className="text-white/80">{existingComplaint?.status_label || 'Черновик'}</div>
                                        </div>
                                        <div>
                                            <div className="text-xs uppercase tracking-wide text-white/30 mb-1">Дата нарушения</div>
                                            <div className="text-white/80">
                                                {form.incident_at ? formatMskToLocal(form.incident_at, { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'}
                                            </div>
                                        </div>
                                        <div>
                                            <div className="text-xs uppercase tracking-wide text-white/30 mb-1">Медиа</div>
                                            <div className="text-white/80 break-all">{form.media.trim() || '—'}</div>
                                        </div>
                                    </div>

                                    <CommandBlock
                                        lines={[
                                            {
                                                label: 'Команды жалобы',
                                                value: buildComplaintCommandsPreview(form.punishments, actorName, {
                                                    media: form.media,
                                                    incident_at: form.incident_at,
                                                }),
                                            },
                                            {
                                                label: 'Тексты жалобы',
                                                value: buildComplaintMessagesPreview(form.punishments),
                                            },
                                        ]}
                                        onCopy={onCopyCommand}
                                    />

                                    <div className="flex flex-col gap-3 pt-2">
                                        {existingComplaint?.status === 'issued' || existingComplaint?.status === 'completed' ? (
                                            <button
                                                onClick={onSubmitIssuedSave}
                                                disabled={submittingTarget !== null}
                                                className="w-full px-4 py-3 rounded-xl bg-blue-500/15 border border-blue-500/30 text-blue-300 font-semibold hover:bg-blue-500/25 transition-colors disabled:opacity-50"
                                            >
                                                {submittingTarget === 'save' ? 'Сохранение...' : 'Сохранить изменения'}
                                            </button>
                                        ) : (
                                            <>
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
                                            </>
                                        )}
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

export default function ComplaintsPage() {
    const { user } = useOutletContext<OutletUserContext>();
    const navigate = useNavigate();
    const { toast, showToast, closeToast } = usePopupToast(2400);
    const { confirm, dialogProps } = useConfirmDialog();
    const { servers: gameServers, serversById } = useGameServers();

    const canViewQueue = hasPerm(user, 'complaints.queue.view');
    const canViewHistory = hasPerm(user, 'complaints.history.view');
    const canCreate = hasPerm(user, 'complaints.create');

    const [activeTab, setActiveTab] = React.useState<ComplaintsTab>(() => (canViewQueue ? 'queue' : 'history'));
    const [queueItems, setQueueItems] = React.useState<ComplaintListItem[]>([]);
    const [historyItems, setHistoryItems] = React.useState<ComplaintListItem[]>([]);
    const [queueLoading, setQueueLoading] = React.useState(true);
    const [historyLoading, setHistoryLoading] = React.useState(false);
    const [historyPage, setHistoryPage] = React.useState(1);
    const [historyTotalPages, setHistoryTotalPages] = React.useState(1);
    const [historyTotal, setHistoryTotal] = React.useState(0);
    const [historyFilters, setHistoryFilters] = React.useState<HistoryFiltersState>(emptyHistoryFilters);
    const [editorOpen, setEditorOpen] = React.useState(false);
    const [editorMode, setEditorMode] = React.useState<'create' | 'edit'>('create');
    const [editorLoading, setEditorLoading] = React.useState(false);
    const [editingComplaint, setEditingComplaint] = React.useState<ComplaintDetail['complaint'] | null>(null);
    const [formState, setFormState] = React.useState<ComplaintFormState>(() => createEmptyFormState());
    const [submittingTarget, setSubmittingTarget] = React.useState<'draft' | 'pending' | 'save' | null>(null);
    const [deletingId, setDeletingId] = React.useState<string | null>(null);

    const actorName = user?.nickname || '';
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

    const normalizeForm = React.useCallback((detail?: ComplaintDetail | null): ComplaintFormState => {
        if (!detail) return createFormState();
        return {
            server: String(detail.complaint.server),
            media: detail.complaint.media || '',
            complaint_link: detail.complaint.complaint_link || '',
            incident_at: toDatetimeLocalValue(detail.complaint.incident_at),
            punishments: (detail.punishments.length > 0 ? detail.punishments : [emptyPunishment()]).map((item) => ({
                punishment_type: item.punishment_type,
                static: String(item.static ?? ''),
                duration: item.duration === null || item.duration === undefined ? '' : String(item.duration),
                reason: item.reason || '',
            })),
        };
    }, []);

    const fetchQueue = React.useCallback(async () => {
        setQueueLoading(true);
        try {
            const response = await apiFetch('/api/complaints/queue');
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payload, 'Не удалось загрузить очередь жалоб'));
            }
            const json = await response.json() as unknown;
            const data = unwrapApiData<unknown>(json);
            const items = Array.isArray(data)
                ? data
                : Array.isArray((data as { items?: ComplaintListItem[] } | null)?.items)
                    ? (data as { items: ComplaintListItem[] }).items
                    : [];
            setQueueItems(items as ComplaintListItem[]);
        } catch (error) {
            console.error('Failed to fetch complaints queue:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось загрузить очередь жалоб', 'error');
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
            const response = await apiFetch(`/api/complaints/history?${params.toString()}`);
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payload, 'Не удалось загрузить историю жалоб'));
            }
            const json = await response.json() as unknown;
            const data = unwrapApiData<unknown>(json);
            const normalized = (Array.isArray(data) ? { items: data } : data) as Partial<HistoryPayload>;
            setHistoryItems((normalized.items || []) as ComplaintListItem[]);
            setHistoryTotal(normalized.total || 0);
            setHistoryPage(normalized.page || 1);
            setHistoryTotalPages(normalized.pages || 1);
        } catch (error) {
            console.error('Failed to fetch complaints history:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось загрузить историю жалоб', 'error');
        } finally {
            setHistoryLoading(false);
        }
    }, [showToast]);

    const fetchComplaintDetail = React.useCallback(async (complaintId: string) => {
        const response = await apiFetch(`/api/complaints/${complaintId}`);
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            throw new Error(getApiErrorMessage(payload, 'Не удалось загрузить жалобу'));
        }

        const json = await response.json() as unknown;
        const data = unwrapApiData<unknown>(json) as Partial<ComplaintDetail & ComplaintListItem>;
        const complaint = (data as ComplaintDetail).complaint || (data as ComplaintListItem);
        const punishments = Array.isArray((data as ComplaintDetail).punishments)
            ? (data as ComplaintDetail).punishments
            : [];

        return {
            complaint: complaint as ComplaintDetail['complaint'],
            punishments: punishments as ComplaintPunishmentItem[],
            aggregate_command: (data as ComplaintDetail).aggregate_command ?? (complaint as ComplaintSummary).aggregate_command,
            aggregate_message: (data as ComplaintDetail).aggregate_message ?? (complaint as ComplaintSummary).aggregate_message,
        } satisfies ComplaintDetail;
    }, []);

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
        setEditingComplaint(null);
        setFormState(createFormState());
        setSubmittingTarget(null);
    }, [createFormState]);

    const openCreate = React.useCallback(() => {
        setEditorMode('create');
        setEditingComplaint(null);
        setFormState(createFormState());
        setEditorOpen(true);
    }, [createFormState]);

    const openEdit = React.useCallback(async (complaintId: string) => {
        setEditorMode('edit');
        setEditorOpen(true);
        setEditorLoading(true);
        try {
            const detail = await fetchComplaintDetail(complaintId);
            setEditingComplaint(detail.complaint);
            setFormState(normalizeForm(detail));
        } catch (error) {
            console.error('Failed to load complaint detail:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось загрузить жалобу', 'error');
            closeEditor();
        } finally {
            setEditorLoading(false);
        }
    }, [closeEditor, fetchComplaintDetail, normalizeForm, showToast]);

    const serializePayload = React.useCallback((
        targetStatus: 'draft' | 'pending' | null,
        form: ComplaintFormState,
        allowedInactiveServerId?: number,
    ) => {
        const server = Number(form.server);
        const selectedServer = Number.isInteger(server) ? serversById[server] : undefined;
        if (!Number.isInteger(server) || server < 1 || !selectedServer || (!selectedServer.is_active && allowedInactiveServerId !== server)) {
            showToast('Выберите сервер', 'error');
            return null;
        }

        if (!form.incident_at.trim()) {
            showToast('Укажите дату и время нарушения', 'error');
            return null;
        }

        if (!form.media.trim()) {
            showToast('Укажите медиа', 'error');
            return null;
        }

        const punishments: ComplaintCreateInput['punishments'] = [];
        for (const punishment of form.punishments) {
            const staticValue = Number(punishment.static);
            if (!Number.isInteger(staticValue) || staticValue <= 0) {
                showToast('Заполните статик нарушителя', 'error');
                return null;
            }
            if (!punishment.reason.trim()) {
                showToast('Заполните причину наказания', 'error');
                return null;
            }
            if (punishment.punishment_type !== 'warn') {
                const durationValue = Number(punishment.duration);
                if (!Number.isInteger(durationValue) || durationValue <= 0) {
                    showToast('Заполните время наказания', 'error');
                    return null;
                }
                punishments.push({
                    punishment_type: punishment.punishment_type,
                    static: staticValue,
                    duration: durationValue,
                    reason: punishment.reason.trim(),
                });
            } else {
                punishments.push({
                    punishment_type: punishment.punishment_type,
                    static: staticValue,
                    duration: null,
                    reason: punishment.reason.trim(),
                });
            }
        }

        if (punishments.length === 0) {
            showToast('Добавьте хотя бы одно наказание', 'error');
            return null;
        }

        const payload: ComplaintUpdateInput = {
            server,
            media: form.media.trim(),
            complaint_link: form.complaint_link.trim() || null,
            incident_at: form.incident_at.trim(),
            punishments,
        };

        if (targetStatus) {
            payload.target_status = targetStatus;
        }

        return payload;
    }, [serversById, showToast]);

    const copyCommand = React.useCallback(async (value: string) => {
        try {
            await navigator.clipboard.writeText(value);
            showToast('Скопировано');
        } catch {
            showToast('Не удалось скопировать', 'error');
        }
    }, [showToast]);

    const updatePunishments = React.useCallback((updater: (items: ComplaintPunishmentFormState[]) => ComplaintPunishmentFormState[]) => {
        setFormState((prev) => ({ ...prev, punishments: updater(prev.punishments) }));
    }, []);

    const deleteComplaint = React.useCallback(async (complaintId: string) => {
        setDeletingId(complaintId);
        try {
            const response = await apiFetch(`/api/complaints/${complaintId}`, {
                method: 'DELETE',
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payload, 'Не удалось удалить жалобу'));
            }
            showToast('Жалоба удалена');
            closeEditor();
            if (canViewQueue) {
                await fetchQueue();
            }
            if (canViewHistory) {
                await fetchHistory(historyPageRef.current);
            }
        } catch (error) {
            console.error('Failed to delete complaint:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось удалить жалобу', 'error');
        } finally {
            setDeletingId(null);
        }
    }, [canViewHistory, canViewQueue, closeEditor, fetchHistory, fetchQueue, historyPageRef, showToast]);

    const requestRemovePunishment = React.useCallback(async (index: number) => {
        if (formState.punishments.length > 1) {
            updatePunishments((items) => items.filter((_, itemIndex) => itemIndex !== index));
            return;
        }

        if (editorMode !== 'edit' || !editingComplaint) {
            showToast('Минимум одно наказание', 'error');
            return;
        }

        const confirmed = await confirm({
            title: 'Удалить жалобу?',
            message: (
                <>
                    Последнее наказание будет удалено, поэтому вся жалоба для статика{' '}
                    <span className="text-white font-semibold">{editingComplaint.id}</span> будет удалена полностью.
                </>
            ),
            tone: 'danger',
            confirmLabel: 'Удалить',
        });

        if (!confirmed) return;

        await deleteComplaint(editingComplaint.id);
    }, [confirm, deleteComplaint, editingComplaint, editorMode, formState.punishments.length, showToast, updatePunishments]);

    const submitComplaint = React.useCallback(async (targetStatus: 'draft' | 'pending') => {
        const payload = serializePayload(targetStatus, formState, editorMode === 'edit' ? editingComplaint?.server : undefined);
        if (!payload) return;

        setSubmittingTarget(targetStatus);
        try {
            const response = await apiFetch(
                editorMode === 'edit' && editingComplaint ? `/api/complaints/${editingComplaint.id}` : '/api/complaints',
                {
                    method: editorMode === 'edit' && editingComplaint ? 'PATCH' : 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                },
            );

            if (!response.ok) {
                const payloadError = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payloadError, 'Не удалось сохранить жалобу'));
            }

            showToast(targetStatus === 'draft' ? 'Черновик сохранен' : 'Жалоба отправлена к выдаче');
            closeEditor();
            if (canViewQueue) {
                await fetchQueue();
            }
            if (activeTab === 'history' && canViewHistory) {
                await fetchHistory(historyPageRef.current);
            }
        } catch (error) {
            console.error('Failed to submit complaint:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось сохранить жалобу', 'error');
        } finally {
            setSubmittingTarget(null);
        }
    }, [activeTab, canViewHistory, canViewQueue, closeEditor, editorMode, editingComplaint, fetchHistory, fetchQueue, formState, serializePayload, showToast]);

    const saveIssuedComplaint = React.useCallback(async () => {
        if (editorMode !== 'edit' || !editingComplaint) return;

        const payload = serializePayload(null, formState, editingComplaint.server);
        if (!payload) return;

        setSubmittingTarget('save');
        try {
            const response = await apiFetch(`/api/complaints/${editingComplaint.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            if (!response.ok) {
                const payloadError = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payloadError, 'Не удалось сохранить жалобу'));
            }

            showToast('Жалоба обновлена');
            closeEditor();
            if (canViewQueue) {
                await fetchQueue();
            }
            if (canViewHistory) {
                await fetchHistory(historyPageRef.current);
            }
        } catch (error) {
            console.error('Failed to save issued complaint:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось сохранить жалобу', 'error');
        } finally {
            setSubmittingTarget(null);
        }
    }, [canViewHistory, canViewQueue, closeEditor, editingComplaint, editorMode, fetchHistory, fetchQueue, formState, historyPageRef, serializePayload, showToast]);

    const submitComplaintRecord = React.useCallback(async (complaintId: string) => {
        try {
            const response = await apiFetch(`/api/complaints/${complaintId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target_status: 'pending' }),
            });
            if (!response.ok) {
                const errorPayload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(errorPayload, 'Не удалось отправить жалобу к выдаче'));
            }

            showToast('Жалоба отправлена к выдаче');
            if (canViewQueue) {
                await fetchQueue();
            }
            if (canViewHistory) {
                await fetchHistory(historyPageRef.current);
            }
        } catch (error) {
            console.error('Failed to submit complaint record:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось отправить жалобу к выдаче', 'error');
        }
    }, [canViewHistory, canViewQueue, fetchHistory, fetchQueue, historyPageRef, showToast]);

    const issueComplaint = React.useCallback(async (complaintId: string) => {
        try {
            const response = await apiFetch(`/api/complaints/${complaintId}/issue`, {
                method: 'POST',
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(getApiErrorMessage(payload, 'Не удалось выдать жалобу'));
            }
            showToast('Жалоба выдана');
            await fetchQueue();
            if (canViewHistory) {
                await fetchHistory(1);
            }
        } catch (error) {
            console.error('Failed to issue complaint:', error);
            showToast(error instanceof Error ? error.message : 'Не удалось выдать жалобу', 'error');
        }
    }, [canViewHistory, fetchHistory, fetchQueue, showToast]);

    const deleteComplaintRecord = React.useCallback(async (complaint: ComplaintListItem) => {
        const confirmed = await confirm({
            title: 'Удалить жалобу?',
            message: (
                <>
                    Будет удалена вся жалоба для статиков{' '}
                    <span className="text-white font-semibold">
                        {complaint.punishments.map((item) => item.static).join(', ')}
                    </span>
                    . В ней {complaint.punishments.length} наказаний.
                </>
            ),
            tone: 'danger',
            confirmLabel: 'Удалить',
        });

        if (!confirmed) return;

        await deleteComplaint(complaint.id);
    }, [confirm, deleteComplaint]);

    const renderComplaintActions = (item: ComplaintListItem) => {
        const buttons: React.ReactNode[] = [];

        if (item.status === 'draft' && item.can_submit) {
            buttons.push(
                <button
                    key="submit"
                    onClick={() => void submitComplaintRecord(item.id)}
                    className="px-3 py-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 transition-colors text-xs font-semibold whitespace-nowrap"
                >
                    Отправить к выдаче
                </button>,
            );
        }

        if (item.status === 'pending' && item.can_issue) {
            buttons.push(
                <button
                    key="issue"
                    onClick={() => void issueComplaint(item.id)}
                    className="px-3 py-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 transition-colors text-xs font-semibold whitespace-nowrap"
                >
                    Выдать
                </button>,
            );
        }

        if (item.can_edit) {
            buttons.push(
                <button
                    key="edit"
                    onClick={() => void openEdit(item.id)}
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
                    onClick={() => void deleteComplaintRecord(item)}
                    disabled={deletingId === item.id}
                    className="p-2 rounded-lg border border-red-500/20 bg-red-500/10 text-red-300 hover:bg-red-500/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    title="Удалить жалобу"
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

    return (
        <div className="space-y-6 animate-[fadeIn_0.5s_ease-in-out] -mx-[calc(50vw-50%)] px-6 lg:px-12 pr-10 lg:pr-16">
            <div className="flex items-center justify-between gap-4">
                <h2 className="text-3xl font-bold flex items-center gap-2">
                    <span className="w-1 h-8 bg-[#8b5cf6] rounded-full inline-block" />
                    Жалобы
                </h2>
                {canCreate && (
                    <button
                        onClick={openCreate}
                        className="inline-flex items-center gap-2 px-4 py-3 rounded-xl border border-blue-500/20 bg-blue-500/10 text-blue-300 font-semibold hover:bg-blue-500/20 transition-colors"
                    >
                        <Plus className="w-4 h-4" />
                        Создать жалобу
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
                        <div className="p-10 text-center text-white/40">Нет активных жалоб</div>
                    ) : (
                        <div className="overflow-visible">
                            <table className="w-full text-left border-collapse">
                                <thead className="bg-[#1a1a1a]/80 border-b border-white/5 text-xs text-white/40 font-bold uppercase tracking-wider">
                                    <tr>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">ЖАЛОБА / СЕРВЕР</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">НАКАЗАНИЯ</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">PR ASSISTANT</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">ДАТА</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">СТАТУС</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">МЕДИА</th>
                                        <th className="px-6 py-4 whitespace-nowrap">ССЫЛКА</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap">КОМАНДА / ТЕКСТ</th>
                                        <th className="px-6 py-4 font-semibold whitespace-nowrap text-right">ДЕЙСТВИЕ</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-white/5">
                                    {queueItems.map((item) => (
                                        <tr key={item.id} className="hover:bg-white/5 transition-colors align-top">
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <div className="font-bold text-white/90">Жалоба #{item.id}</div>
                                                <div className="text-xs text-white/40 mt-1">{formatGameServerLabel(item.server, 'full', serversById)}</div>
                                                <div className="mt-3 flex flex-wrap gap-1.5">
                                                    {item.punishments.map((punishment) => (
                                                        <span
                                                            key={punishment.id}
                                                            className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.03] px-2 py-1 text-[11px] font-semibold text-white/75"
                                                        >
                                                            #{punishment.static}
                                                        </span>
                                                    ))}
                                                </div>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <div className="space-y-2">
                                                    {item.punishments.map((punishment) => (
                                                        <div
                                                            key={punishment.id}
                                                            className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 space-y-1.5"
                                                        >
                                                            <div className="flex flex-wrap items-center gap-2">
                                                                <span className="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 text-[11px] font-semibold text-white/70">
                                                                    {formatComplaintPunishmentLabel(punishment.punishment_type)}
                                                                </span>
                                                                <span className="text-xs font-semibold text-white/80">#{punishment.static}</span>
                                                                <span className="text-xs text-white/45">
                                                                    {formatComplaintDurationLabel(punishment.punishment_type, punishment.duration)}
                                                                </span>
                                                            </div>
                                                            <div className="text-xs text-white/60 break-words whitespace-pre-wrap">{punishment.reason}</div>
                                                        </div>
                                                    ))}
                                                </div>
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
                                                <div className="text-sm text-white/70">{getComplaintDisplayDate(item)}</div>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <ComplaintStatusBadge status={item.status} label={item.status_label} />
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <div className="max-w-[220px] text-xs text-white/70 break-words whitespace-pre-wrap">{item.media || '—'}</div>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                {item.complaint_link ? (
                                                    <a
                                                        href={item.complaint_link}
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
                                                <CommandBlock
                                                    lines={[
                                                        {
                                                            label: 'Команды',
                                                            value: item.aggregate_command || buildComplaintCommandsPreview(
                                                                item.punishments,
                                                                getComplaintPreviewActorName(item),
                                                                { media: item.media, incident_at: item.incident_at },
                                                            ),
                                                        },
                                                        {
                                                            label: 'Тексты',
                                                            value: item.aggregate_message || buildComplaintMessagesPreview(item.punishments),
                                                        },
                                                    ]}
                                                    onCopy={(value) => void copyCommand(value)}
                                                />
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-right">
                                                {renderComplaintActions(item)}
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
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">ЖАЛОБА / СЕРВЕР</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">НАКАЗАНИЯ</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">PR ASSISTANT</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">ДАТА</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">СТАТУС</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">МЕДИА</th>
                                            <th className="px-6 py-4 whitespace-nowrap">ССЫЛКА</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap">КОМАНДА / ТЕКСТ</th>
                                            <th className="px-6 py-4 font-semibold whitespace-nowrap text-right">ДЕЙСТВИЕ</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-white/5">
                                        {historyItems.map((item) => (
                                            <tr key={item.id} className="hover:bg-white/5 transition-colors align-top">
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="font-bold text-white/90">Жалоба #{item.id}</div>
                                                    <div className="text-xs text-white/40 mt-1">{formatGameServerLabel(item.server, 'full', serversById)}</div>
                                                    <div className="mt-3 flex flex-wrap gap-1.5">
                                                        {item.punishments.map((punishment) => (
                                                            <span
                                                                key={punishment.id}
                                                                className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.03] px-2 py-1 text-[11px] font-semibold text-white/75"
                                                            >
                                                                #{punishment.static}
                                                            </span>
                                                        ))}
                                                    </div>
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="space-y-2">
                                                        {item.punishments.map((punishment) => (
                                                            <div
                                                                key={punishment.id}
                                                                className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 space-y-1.5"
                                                            >
                                                                <div className="flex flex-wrap items-center gap-2">
                                                                    <span className="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 text-[11px] font-semibold text-white/70">
                                                                        {formatComplaintPunishmentLabel(punishment.punishment_type)}
                                                                    </span>
                                                                    <span className="text-xs font-semibold text-white/80">#{punishment.static}</span>
                                                                    <span className="text-xs text-white/45">
                                                                        {formatComplaintDurationLabel(punishment.punishment_type, punishment.duration)}
                                                                    </span>
                                                                </div>
                                                                <div className="text-xs text-white/60 break-words whitespace-pre-wrap">{punishment.reason}</div>
                                                            </div>
                                                        ))}
                                                    </div>
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
                                                    <div className="text-sm text-white/70">{getComplaintDisplayDate(item)}</div>
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <ComplaintStatusBadge status={item.status} label={item.status_label} />
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    <div className="max-w-[220px] text-xs text-white/70 break-words whitespace-pre-wrap">{item.media || '—'}</div>
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap">
                                                    {item.complaint_link ? (
                                                        <a
                                                            href={item.complaint_link}
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
                                                    <CommandBlock
                                                        lines={[
                                                            {
                                                                label: 'Команды',
                                                                value: item.aggregate_command || buildComplaintCommandsPreview(
                                                                    item.punishments,
                                                                    getComplaintPreviewActorName(item),
                                                                    { media: item.media, incident_at: item.incident_at },
                                                                ),
                                                            },
                                                            {
                                                                label: 'Тексты',
                                                                value: item.aggregate_message || buildComplaintMessagesPreview(item.punishments),
                                                            },
                                                        ]}
                                                        onCopy={(value) => void copyCommand(value)}
                                                    />
                                                </td>
                                                <td className="px-6 py-4 whitespace-nowrap text-right">
                                                    {renderComplaintActions(item)}
                                                </td>
                                            </tr>
                                        ))}
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

            <ComplaintFormModal
                isOpen={editorOpen}
                loading={editorLoading}
                title={editorMode === 'edit' ? 'Редактирование жалобы' : 'Создание жалобы'}
                actorName={actorName}
                form={formState}
                existingComplaint={editingComplaint}
                submittingTarget={submittingTarget}
                serverOptions={serverOptions}
                onClose={closeEditor}
                onChange={(updates) => setFormState((prev) => ({ ...prev, ...updates }))}
                onAddPunishment={() => updatePunishments((items) => [...items, emptyPunishment()])}
                onRequestRemovePunishment={requestRemovePunishment}
                onSubmitDraft={() => void submitComplaint('draft')}
                onSubmitPending={() => void submitComplaint('pending')}
                onSubmitIssuedSave={() => void saveIssuedComplaint()}
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
