import React from 'react';
import { AlertCircle, Database, Plus, RefreshCw, RotateCcw, Save, Server, Trash2 } from 'lucide-react';

import { apiFetch } from '../../../api/client';
import NotificationToast from '../../../components/feedback/NotificationToast';
import { usePopupToast } from '../../../components/feedback/hooks';
import { getApiErrorMessage, unwrapApiData } from '../../../types/api';

interface GameServerItem {
    id: number;
    full_name: string;
    short_name: string;
    command_name: string;
    sort_order: number;
    is_active: boolean;
}

interface GameServerDraft {
    local_key: string;
    persisted_id: number | null;
    full_name: string;
    short_name: string;
    command_name: string;
    sort_order: string;
    is_active: boolean;
    is_new: boolean;
}

interface SavePayloadItem {
    id?: number;
    full_name: string;
    short_name: string;
    command_name: string;
    sort_order: number;
    is_active: boolean;
}

const emptyDraft = (localKey: string, sortOrder: number): GameServerDraft => ({
    local_key: localKey,
    persisted_id: null,
    full_name: '',
    short_name: '',
    command_name: '',
    sort_order: String(sortOrder),
    is_active: true,
    is_new: true,
});

const normalizeGameServers = (payload: unknown): GameServerItem[] => {
    const data = unwrapApiData<unknown>(payload);
    if (!Array.isArray(data)) return [];

    return data
        .map((item) => {
            if (!item || typeof item !== 'object') return null;
            const raw = item as Partial<GameServerItem>;
            const id = Number(raw.id);
            if (!Number.isFinite(id)) return null;
            return {
                id,
                full_name: String(raw.full_name ?? ''),
                short_name: String(raw.short_name ?? ''),
                command_name: String(raw.command_name ?? ''),
                sort_order: Number(raw.sort_order ?? id),
                is_active: Boolean(raw.is_active),
            };
        })
        .filter((item): item is GameServerItem => Boolean(item))
        .sort((left, right) => (left.sort_order - right.sort_order) || (left.id - right.id));
};

const toDraft = (item: GameServerItem): GameServerDraft => ({
    local_key: `server-${item.id}`,
    persisted_id: item.id,
    full_name: item.full_name,
    short_name: item.short_name,
    command_name: item.command_name,
    sort_order: String(item.sort_order),
    is_active: item.is_active,
    is_new: false,
});

const toPayloadItem = (draft: GameServerDraft): SavePayloadItem | null => {
    const sortOrder = Number(draft.sort_order);
    if (!Number.isInteger(sortOrder) || sortOrder <= 0) return null;

    const payload: SavePayloadItem = {
        full_name: draft.full_name.trim(),
        short_name: draft.short_name.trim(),
        command_name: draft.command_name.trim(),
        sort_order: sortOrder,
        is_active: draft.is_active,
    };

    if (draft.persisted_id != null) {
        payload.id = draft.persisted_id;
    }

    return payload;
};

const validateDraft = (draft: GameServerDraft): string | null => {
    if (!draft.full_name.trim()) return 'Полное название обязательно';
    if (!draft.short_name.trim()) return 'Короткое название обязательно';
    if (!draft.command_name.trim()) return 'Командное имя обязательно';

    const sortOrder = Number(draft.sort_order);
    if (!Number.isInteger(sortOrder) || sortOrder <= 0) return 'Порядок должен быть положительным целым числом';

    return null;
};

const getNextSortOrder = (rows: GameServerDraft[]) => {
    const maxSort = rows.reduce((max, row) => Math.max(max, Number(row.sort_order) || 0), 0);
    return maxSort + 1;
};

const getSortedRows = (rows: GameServerDraft[]) => rows
    .slice()
    .sort((left, right) => {
        const sortDiff = (Number(left.sort_order) || 0) - (Number(right.sort_order) || 0);
        if (sortDiff !== 0) return sortDiff;

        const leftId = left.persisted_id ?? Number.MAX_SAFE_INTEGER;
        const rightId = right.persisted_id ?? Number.MAX_SAFE_INTEGER;
        if (leftId !== rightId) return leftId - rightId;

        return left.local_key.localeCompare(right.local_key);
    });

const SiteManagement = () => {
    const { toast, showToast, closeToast } = usePopupToast(3200);
    const [rows, setRows] = React.useState<GameServerDraft[]>([]);
    const [loading, setLoading] = React.useState(true);
    const [saving, setSaving] = React.useState(false);
    const [error, setError] = React.useState<string | null>(null);
    const [draftCounter, setDraftCounter] = React.useState(1);

    const loadCatalog = React.useCallback(async () => {
        setLoading(true);
        setError(null);

        try {
            const response = await apiFetch('/api/game-servers');
            const data = await response.json().catch(() => ({} as unknown));
            if (!response.ok) {
                throw new Error(getApiErrorMessage(data, 'Не удалось загрузить каталог серверов'));
            }

            const catalog = normalizeGameServers(data);
            setRows(catalog.map((item) => toDraft(item)));
            setDraftCounter(1);
        } catch (loadError: unknown) {
            const message = loadError instanceof Error ? loadError.message : 'Не удалось загрузить каталог серверов';
            setError(message);
            showToast(message, 'error');
        } finally {
            setLoading(false);
        }
    }, [showToast]);

    React.useEffect(() => {
        void loadCatalog();
    }, [loadCatalog]);

    const addRow = () => {
        const localKey = `draft-${draftCounter}`;
        setDraftCounter((current) => current + 1);
        setRows((current) => [...current, emptyDraft(localKey, getNextSortOrder(current))]);
    };

    const updateRow = (localKey: string, updater: (draft: GameServerDraft) => GameServerDraft) => {
        setRows((current) => current.map((row) => (row.local_key === localKey ? updater(row) : row)));
    };

    const removeDraft = (localKey: string) => {
        setRows((current) => current.filter((row) => row.local_key !== localKey));
    };

    const deactivateSavedRow = (localKey: string) => {
        updateRow(localKey, (draft) => ({ ...draft, is_active: false }));
    };

    const restoreSavedRow = (localKey: string) => {
        updateRow(localKey, (draft) => ({ ...draft, is_active: true }));
    };

    const handleSave = async () => {
        const validationError = rows.map(validateDraft).find(Boolean) ?? null;
        if (validationError) {
            setError(validationError);
            showToast(validationError, 'error');
            return;
        }

        const payloadItems = getSortedRows(rows)
            .map(toPayloadItem)
            .filter((item): item is SavePayloadItem => Boolean(item));

        setSaving(true);
        setError(null);

        try {
            const response = await apiFetch('/api/guild/game-servers', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: payloadItems }),
            });
            const data = await response.json().catch(() => ({} as unknown));
            if (!response.ok) {
                throw new Error(getApiErrorMessage(data, 'Не удалось сохранить каталог серверов'));
            }

            const catalog = normalizeGameServers(data);
            setRows(catalog.map((item) => toDraft(item)));
            setDraftCounter(1);
            showToast('Каталог серверов сохранён');
        } catch (saveError: unknown) {
            const message = saveError instanceof Error ? saveError.message : 'Не удалось сохранить каталог серверов';
            setError(message);
            showToast(message, 'error');
        } finally {
            setSaving(false);
        }
    };

    const activeCount = rows.filter((row) => row.is_active).length;
    const inactiveCount = rows.length - activeCount;

    return (
        <div className="space-y-6 animate-[fadeIn_0.3s_ease-in-out]">
            <div className="flex flex-col gap-4 border-b border-white/10 pb-6">
                <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-4">
                        <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-cyan-500/30 bg-cyan-500/15 text-cyan-100">
                            <Server className="h-6 w-6" />
                        </div>
                        <div>
                            <h2 className="text-2xl font-bold text-white">Игровые сервера</h2>
                            <p className="text-white/60">Единый каталог для workflows и weekly payout.</p>
                        </div>
                    </div>

                    <button
                        type="button"
                        onClick={() => void loadCatalog()}
                        className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-white/10"
                    >
                        <RefreshCw className="h-4 w-4" />
                        Обновить
                    </button>
                </div>
            </div>

            <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/5 bg-[#1e1e1e] p-4">
                <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white/70">
                    <Database className="h-4 w-4" />
                    Всего: <span className="font-semibold text-white">{rows.length}</span>
                </div>
                <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1.5 text-sm text-emerald-100">
                    Активных: <span className="font-semibold text-white">{activeCount}</span>
                </div>
                <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white/70">
                    Неактивных: <span className="font-semibold text-white">{inactiveCount}</span>
                </div>
                <button
                    type="button"
                    onClick={addRow}
                    className="ml-auto inline-flex items-center gap-2 rounded-xl border border-fuchsia-500/20 bg-fuchsia-500/15 px-4 py-2.5 text-sm font-medium text-fuchsia-100 transition hover:bg-fuchsia-500/20"
                >
                    <Plus className="h-4 w-4" />
                    Добавить сервер
                </button>
            </div>

            {error && (
                <div className="flex items-start gap-3 rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <div>{error}</div>
                </div>
            )}

            <div className="rounded-2xl border border-white/5 bg-[#1e1e1e] overflow-hidden">
                {loading ? (
                    <div className="p-8 text-center text-white/40">Загрузка...</div>
                ) : rows.length === 0 ? (
                    <div className="p-8 text-center text-white/40">Каталог пуст</div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="min-w-full text-sm">
                            <thead className="bg-[#242424] text-left text-xs uppercase tracking-[0.16em] text-white/40">
                                <tr>
                                    <th className="px-4 py-3">ID</th>
                                    <th className="px-4 py-3">Полное название</th>
                                    <th className="px-4 py-3">Короткое</th>
                                    <th className="px-4 py-3">Команда</th>
                                    <th className="px-4 py-3">Порядок</th>
                                    <th className="px-4 py-3">Статус</th>
                                    <th className="px-4 py-3 text-right">Действия</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-white/5">
                                {getSortedRows(rows).map((row) => (
                                    <tr
                                        key={row.local_key}
                                        data-testid={`game-server-row-${row.local_key}`}
                                        className={`align-top hover:bg-white/[0.02] ${row.is_active ? '' : 'bg-white/[0.02]'}`}
                                    >
                                        <td className="px-4 py-3">
                                            <div
                                                data-testid={`game-server-id-${row.local_key}`}
                                                className={`inline-flex min-w-[120px] items-center justify-center rounded-xl border px-3 py-2 text-sm font-medium ${row.persisted_id == null
                                                    ? 'border-dashed border-white/10 bg-black/10 text-white/35'
                                                    : 'border-white/10 bg-black/20 text-white/80'
                                                    }`}
                                            >
                                                {row.persisted_id == null ? 'Будет назначен' : row.persisted_id}
                                            </div>
                                        </td>
                                        <td className="px-4 py-3">
                                            <input
                                                data-testid={`game-server-full-${row.local_key}`}
                                                type="text"
                                                value={row.full_name}
                                                onChange={(event) => updateRow(row.local_key, (draft) => ({ ...draft, full_name: event.target.value }))}
                                                placeholder="Majestic #19"
                                                className="w-full min-w-[220px] rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-white outline-none placeholder:text-white/25 focus:border-cyan-500/40"
                                            />
                                        </td>
                                        <td className="px-4 py-3">
                                            <input
                                                data-testid={`game-server-short-${row.local_key}`}
                                                type="text"
                                                value={row.short_name}
                                                onChange={(event) => updateRow(row.local_key, (draft) => ({ ...draft, short_name: event.target.value }))}
                                                placeholder="#19"
                                                className="w-full min-w-[150px] rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-white outline-none placeholder:text-white/25 focus:border-cyan-500/40"
                                            />
                                        </td>
                                        <td className="px-4 py-3">
                                            <input
                                                data-testid={`game-server-command-${row.local_key}`}
                                                type="text"
                                                value={row.command_name}
                                                onChange={(event) => updateRow(row.local_key, (draft) => ({ ...draft, command_name: event.target.value }))}
                                                placeholder="RU19"
                                                className="w-full min-w-[150px] rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-white outline-none placeholder:text-white/25 focus:border-cyan-500/40"
                                            />
                                        </td>
                                        <td className="px-4 py-3">
                                            <input
                                                data-testid={`game-server-sort-${row.local_key}`}
                                                type="number"
                                                value={row.sort_order}
                                                onChange={(event) => updateRow(row.local_key, (draft) => ({ ...draft, sort_order: event.target.value }))}
                                                className="w-28 rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500/40"
                                            />
                                        </td>
                                        <td className="px-4 py-3">
                                            <span
                                                data-testid={`game-server-status-${row.local_key}`}
                                                className={`inline-flex items-center rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${row.is_active
                                                    ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100'
                                                    : 'border-white/10 bg-white/5 text-white/55'
                                                    }`}
                                            >
                                                {row.is_active ? 'Активен' : 'Неактивен'}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3 text-right">
                                            <div className="flex items-center justify-end gap-2">
                                                {row.is_new ? (
                                                    <button
                                                        type="button"
                                                        onClick={() => removeDraft(row.local_key)}
                                                        className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/70 transition hover:bg-white/10"
                                                    >
                                                        <Trash2 className="h-4 w-4" />
                                                        Удалить черновик
                                                    </button>
                                                ) : row.is_active ? (
                                                    <button
                                                        type="button"
                                                        onClick={() => deactivateSavedRow(row.local_key)}
                                                        className="inline-flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-sm text-amber-100 transition hover:bg-amber-500/20"
                                                    >
                                                        <Trash2 className="h-4 w-4" />
                                                        Удалить сервер
                                                    </button>
                                                ) : (
                                                    <button
                                                        type="button"
                                                        onClick={() => restoreSavedRow(row.local_key)}
                                                        className="inline-flex items-center gap-2 rounded-xl border border-cyan-500/20 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-100 transition hover:bg-cyan-500/20"
                                                    >
                                                        <RotateCcw className="h-4 w-4" />
                                                        Восстановить сервер
                                                    </button>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            <div className="flex items-center justify-between gap-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3 text-sm text-white/55">
                <button
                    type="button"
                    onClick={() => void handleSave()}
                    disabled={saving || loading}
                    className="inline-flex items-center gap-2 rounded-xl border border-fuchsia-500/20 bg-fuchsia-500/15 px-4 py-2.5 font-medium text-fuchsia-100 transition hover:bg-fuchsia-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    {saving ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    Сохранить каталог
                </button>
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
};

export default SiteManagement;
