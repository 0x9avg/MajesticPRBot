import React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { AlertTriangle, LogOut, RefreshCw, ShieldAlert } from 'lucide-react';

import {
    apiFetch,
    clearSiteMaintenanceState,
    getAccessToken,
    getSiteMaintenanceMessage,
    readSiteMaintenanceMessage,
    setAccessToken,
    tryRefresh,
} from '../api/client';

void React;

const FALLBACK_MESSAGE = 'На сайте ведутся технические работы. Попробуйте позже.';

type MaintenanceLocationState =
    | string
    | {
        message?: string;
    }
    | null
    | undefined;

function normalizeMessage(value: unknown): string | null {
    if (typeof value === 'string') {
        const trimmed = value.trim();
        return trimmed ? trimmed : null;
    }

    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return null;
    }

    const message = (value as { message?: unknown }).message;
    return typeof message === 'string' && message.trim() ? message.trim() : null;
}

function resolveLocationMessage(state: MaintenanceLocationState): string | null {
    return normalizeMessage(state) ?? (
        state && typeof state === 'object' && !Array.isArray(state)
            ? normalizeMessage((state as { message?: unknown }).message)
            : null
    );
}

export default function MaintenancePage() {
    const navigate = useNavigate();
    const location = useLocation();
    const [message, setMessage] = useState<string>(FALLBACK_MESSAGE);
    const [loadingRefresh, setLoadingRefresh] = useState(false);
    const [loadingLogout, setLoadingLogout] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const locationMessage = useMemo(
        () => resolveLocationMessage(location.state as MaintenanceLocationState),
        [location.state],
    );

    useEffect(() => {
        setMessage(locationMessage || getSiteMaintenanceMessage() || FALLBACK_MESSAGE);
        setError(null);
    }, [locationMessage]);

    const clearLocalAuth = () => {
        setAccessToken(null);
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
        clearSiteMaintenanceState();
    };

    const handleRefresh = async () => {
        setLoadingRefresh(true);
        setError(null);

        try {
            if (!getAccessToken()) {
                const refreshed = await tryRefresh();
                if (!refreshed) {
                    const runtimeMaintenanceMessage = getSiteMaintenanceMessage();
                    if (runtimeMaintenanceMessage) {
                        setMessage(runtimeMaintenanceMessage);
                        return;
                    }

                    clearLocalAuth();
                    navigate('/login', { replace: true });
                    return;
                }
            }

            const response = await apiFetch('/api/auth/me');
            const maintenanceMessage = await readSiteMaintenanceMessage(response);

            if (maintenanceMessage) {
                setMessage(maintenanceMessage);
                return;
            }

            if (response.status === 401 || response.status === 403) {
                clearLocalAuth();
                navigate('/login', { replace: true });
                return;
            }

            if (!response.ok) {
                setError('Не удалось проверить состояние сайта.');
                return;
            }

            clearSiteMaintenanceState();
            navigate('/hub', { replace: true });
        } catch {
            setError('Не удалось проверить состояние сайта.');
        } finally {
            setLoadingRefresh(false);
        }
    };

    const handleLogout = async () => {
        setLoadingLogout(true);
        setError(null);

        try {
            await apiFetch('/api/auth/logout/current', { method: 'POST' });
        } catch {
            // Best effort logout.
        } finally {
            clearLocalAuth();
            navigate('/login', { replace: true });
            setLoadingLogout(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center p-4 relative overflow-hidden bg-[#1a1a1a] text-white">
            <div className="absolute top-0 left-0 w-full h-full overflow-hidden pointer-events-none z-0">
                <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-[#2563eb]/10 rounded-full blur-[100px]" />
                <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-[#e81c5a]/10 rounded-full blur-[100px]" />
            </div>

            <div className="relative z-10 w-full max-w-2xl rounded-3xl border border-white/8 bg-[#242424]/55 p-8 shadow-2xl backdrop-blur-xl animate-[fadeIn_0.45s_ease-in-out]">
                <div className="flex flex-col items-center text-center">
                    <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-amber-500/25 bg-amber-500/10 text-amber-100">
                        <ShieldAlert className="h-8 w-8" />
                    </div>

                    <p className="text-xs uppercase tracking-[0.24em] text-white/35">System notice</p>
                    <h1 className="mt-3 text-3xl font-black bg-gradient-to-r from-[#3b82f6] to-[#e81c5a] bg-clip-text text-transparent">
                        Технические работы
                    </h1>
                    <p className="mt-4 max-w-xl text-sm leading-6 text-white/70">
                        {message}
                    </p>

                    {error && (
                        <div className="mt-6 w-full rounded-2xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-100">
                            {error}
                        </div>
                    )}

                    <div className="mt-8 flex w-full flex-col gap-3 sm:flex-row sm:justify-center">
                        <button
                            type="button"
                            onClick={() => void handleRefresh()}
                            disabled={loadingRefresh}
                            className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#3b82f6]/20 bg-[#2563eb] px-6 py-3 font-medium text-white transition-all hover:bg-[#3b82f6] active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            {loadingRefresh ? <RefreshCw className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                            Обновить
                        </button>

                        <button
                            type="button"
                            onClick={() => void handleLogout()}
                            disabled={loadingLogout}
                            className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-6 py-3 font-medium text-white transition-all hover:bg-white/10 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            {loadingLogout ? <RefreshCw className="h-4 w-4 animate-spin" /> : <LogOut className="h-4 w-4" />}
                            Выйти
                        </button>
                    </div>

                    <div className="mt-8 flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-white/35">
                        <AlertTriangle className="h-4 w-4 text-amber-300/80" />
                        Доступ откроется после завершения работ
                    </div>
                </div>
            </div>
        </div>
    );
}
