import React from 'react';
import { AlertCircle, RefreshCw, Save, ShieldAlert } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';

import { apiFetch } from '../../../api/client';
import NotificationToast from '../../../components/feedback/NotificationToast';
import { usePopupToast } from '../../../components/feedback/hooks';
import { hasPerm } from '../../../rbac/guards';
import { getApiErrorMessage, unwrapApiData } from '../../../types/api';
import type { OutletUserContext } from '../../../types/auth';

const SITE_MAINTENANCE_ENDPOINT = '/api/admin/site-maintenance';

const normalizeMaintenancePayload = (payload: unknown) => {
    const data = unwrapApiData<unknown>(payload);
    if (data && typeof data === 'object' && !Array.isArray(data)) {
        const raw = data as Record<string, unknown>;
        return Boolean(raw.enabled ?? raw.maintenance_enabled);
    }
    return false;
};

const SiteMaintenanceManagement = () => {
    const { user } = useOutletContext<OutletUserContext>();
    const { toast, showToast, closeToast } = usePopupToast(3200);
    const canViewMaintenance = hasPerm(user, 'site.maintenance.view') || hasPerm(user, 'site.maintenance.update');
    const canUpdateMaintenance = hasPerm(user, 'site.maintenance.update');

    const [loading, setLoading] = React.useState(true);
    const [saving, setSaving] = React.useState(false);
    const [error, setError] = React.useState<string | null>(null);
    const [maintenanceEnabled, setMaintenanceEnabled] = React.useState(false);

    const loadMaintenance = React.useCallback(async () => {
        setLoading(true);
        setError(null);

        try {
            const response = await apiFetch(SITE_MAINTENANCE_ENDPOINT);
            const data = await response.json().catch(() => ({} as unknown));
            if (!response.ok) {
                throw new Error(getApiErrorMessage(data, 'Не удалось загрузить режим тех. работ'));
            }

            setMaintenanceEnabled(normalizeMaintenancePayload(data));
        } catch (loadError: unknown) {
            const message = loadError instanceof Error ? loadError.message : 'Не удалось загрузить режим тех. работ';
            setError(message);
            showToast(message, 'error');
        } finally {
            setLoading(false);
        }
    }, [showToast]);

    React.useEffect(() => {
        void loadMaintenance();
    }, [loadMaintenance]);

    const handleSave = async () => {
        if (!canUpdateMaintenance) return;
        setSaving(true);
        setError(null);

        try {
            const response = await apiFetch(SITE_MAINTENANCE_ENDPOINT, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: maintenanceEnabled }),
            });
            const data = await response.json().catch(() => ({} as unknown));
            if (!response.ok) {
                throw new Error(getApiErrorMessage(data, 'Не удалось обновить режим тех. работ'));
            }

            setMaintenanceEnabled(normalizeMaintenancePayload(data));
            showToast('Режим тех. работ обновлён');
        } catch (saveError: unknown) {
            const message = saveError instanceof Error ? saveError.message : 'Не удалось обновить режим тех. работ';
            setError(message);
            showToast(message, 'error');
        } finally {
            setSaving(false);
        }
    };

    if (!canViewMaintenance) {
        return (
            <div className="space-y-6 animate-[fadeIn_0.3s_ease-in-out]">
                <div className="flex items-center gap-4 border-b border-white/10 pb-6">
                    <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-amber-500/30 bg-amber-500/15 text-amber-100">
                        <ShieldAlert className="h-6 w-6" />
                    </div>
                    <div>
                        <h2 className="text-2xl font-bold text-white">Тех. работы</h2>
                        <p className="text-white/60">Режим обслуживания системы.</p>
                    </div>
                </div>
                <div className="rounded-2xl border border-white/5 bg-[#1e1e1e] p-8 text-center text-white/45">
                    Недостаточно прав для просмотра режима тех. работ.
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-6 animate-[fadeIn_0.3s_ease-in-out]">
            <div className="flex flex-col gap-4 border-b border-white/10 pb-6">
                <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-4">
                        <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-amber-500/30 bg-amber-500/15 text-amber-100">
                            <ShieldAlert className="h-6 w-6" />
                        </div>
                        <div>
                            <h2 className="text-2xl font-bold text-white">Тех. работы</h2>
                            <p className="text-white/60">Режим обслуживания системы.</p>
                        </div>
                    </div>

                    <button
                        type="button"
                        onClick={() => void loadMaintenance()}
                        className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-white/10"
                    >
                        <RefreshCw className="h-4 w-4" />
                        Обновить
                    </button>
                </div>
            </div>

            {error && (
                <div className="flex items-start gap-3 rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <div>{error}</div>
                </div>
            )}

            {loading ? (
                <div className="rounded-2xl border border-white/5 bg-[#1e1e1e] p-8 text-center text-white/40">Загрузка...</div>
            ) : (
                <div className="rounded-2xl border border-white/5 bg-[#1e1e1e] p-6">
                    <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
                        <div className="space-y-3">
                            <div className="flex items-center gap-3">
                                <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-amber-500/25 bg-amber-500/10 text-amber-100">
                                    <ShieldAlert className="h-5 w-5" />
                                </div>
                                <div>
                                    <div className="text-sm font-semibold text-white">Технические работы</div>
                                    <div className="text-sm text-white/60">
                                        Включает backend-ответ `SITE_MAINTENANCE` для пользователей без `maintenance.bypass`.
                                    </div>
                                </div>
                            </div>
                            <label className="inline-flex items-center gap-3 rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-white">
                                <input
                                    data-testid="site-maintenance-toggle"
                                    type="checkbox"
                                    checked={maintenanceEnabled}
                                    onChange={(event) => setMaintenanceEnabled(event.target.checked)}
                                    disabled={!canUpdateMaintenance}
                                    className="h-4 w-4 rounded border-white/20 bg-black/20 text-sky-500 focus:ring-sky-500/40"
                                />
                                {maintenanceEnabled ? 'Тех. работы включены' : 'Тех. работы выключены'}
                            </label>
                            {!canUpdateMaintenance && (
                                <div className="text-sm text-white/45">
                                    Изменение режима доступно только с правом `site.maintenance.update`.
                                </div>
                            )}
                        </div>

                        <button
                            type="button"
                            onClick={() => void handleSave()}
                            disabled={saving || !canUpdateMaintenance}
                            className="inline-flex items-center justify-center gap-2 rounded-xl border border-amber-500/20 bg-amber-500/15 px-4 py-2.5 text-sm font-medium text-amber-100 transition hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {saving ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                            Сохранить режим
                        </button>
                    </div>
                </div>
            )}

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

export default SiteMaintenanceManagement;
