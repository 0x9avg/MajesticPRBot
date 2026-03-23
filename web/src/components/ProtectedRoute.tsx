import React from 'react';
import { useState, useEffect } from 'react';
import { Navigate, Outlet, useOutletContext } from 'react-router-dom';
import { getAccessToken, getSiteMaintenanceMessage, tryRefresh } from '../api/client';

void React;

interface ProtectedRouteProps {
    allowedRoles?: string[];
}

function parseTokenPayload(token: string): { role?: string; exp?: number } | null {
    try {
        const parts = token.split('.');
        if (parts.length < 2) return null;

        const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
        const padded = b64.padEnd(b64.length + ((4 - (b64.length % 4)) % 4), '=');
        const decode = typeof atob === 'function' ? atob : null;
        if (!decode) return null;

        return JSON.parse(decode(padded)) as { role?: string; exp?: number };
    } catch {
        return null;
    }
}

export default function ProtectedRoute({ allowedRoles }: ProtectedRouteProps) {
    const parentContext = useOutletContext<unknown>();
    const [authState, setAuthState] = useState<'checking' | 'ok' | 'denied' | 'maintenance'>('checking');

    useEffect(() => {
        let cancelled = false;

        async function checkAuth() {
            const token = getAccessToken();

            if (!token) {
                // No token at all — try refresh (might have HttpOnly cookie)
                const refreshed = await tryRefresh();
                if (!cancelled) {
                    setAuthState(
                        refreshed
                            ? 'ok'
                            : (getSiteMaintenanceMessage() ? 'maintenance' : 'denied')
                    );
                }
                return;
            }

            // Check if token is expired
            const payload = parseTokenPayload(token);
            const isExpired = payload?.exp ? payload.exp < Date.now() / 1000 : false;

            if (isExpired) {
                // Token expired — attempt silent refresh
                const refreshed = await tryRefresh();
                if (!cancelled) {
                    setAuthState(
                        refreshed
                            ? 'ok'
                            : (getSiteMaintenanceMessage() ? 'maintenance' : 'denied')
                    );
                }
                return;
            }

            // Token exists and is not expired
            if (!cancelled) {
                setAuthState('ok');
            }
        }

        checkAuth();
        return () => { cancelled = true; };
    }, []);

    if (authState === 'checking') {
        // Brief loading state while checking / refreshing
        return null;
    }

    if (authState === 'denied') {
        return <Navigate to="/login" replace />;
    }

    if (authState === 'maintenance') {
        return (
            <Navigate
                to="/maintenance"
                replace
                state={{ message: getSiteMaintenanceMessage() }}
            />
        );
    }

    // Role-based access check
    if (allowedRoles && allowedRoles.length > 0) {
        const token = getAccessToken();
        let tokenRole: string | null = null;

        if (token) {
            const payload = parseTokenPayload(token);
            tokenRole = typeof payload?.role === 'string' ? payload.role : null;
        }

        if (!tokenRole) {
            return <Navigate to="/login" replace />;
        }

        if (!allowedRoles.includes(tokenRole)) {
            return <Navigate to="/hub" replace />;
        }
    }

    return <Outlet context={parentContext} />;
}
