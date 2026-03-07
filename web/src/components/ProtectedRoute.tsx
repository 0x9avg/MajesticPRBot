import React, { useState, useEffect } from 'react';
import { Navigate, Outlet, useOutletContext } from 'react-router-dom';
import type { UserContext } from '../types/auth';
import { hydrateAccessTokenFromStorage, tryRefresh } from '../api/client';

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
    const [authState, setAuthState] = useState<'checking' | 'ok' | 'denied'>('checking');

    useEffect(() => {
        let cancelled = false;

        async function checkAuth() {
            const token = localStorage.getItem('access_token') || hydrateAccessTokenFromStorage();

            if (!token) {
                // No token at all — try refresh (might have HttpOnly cookie)
                const refreshed = await tryRefresh();
                if (!cancelled) {
                    setAuthState(refreshed ? 'ok' : 'denied');
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
                    setAuthState(refreshed ? 'ok' : 'denied');
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

    // Role-based access check
    if (allowedRoles && allowedRoles.length > 0) {
        const token = localStorage.getItem('access_token') || hydrateAccessTokenFromStorage();
        let tokenRole: string | null = null;
        let cachedRole: string | null = null;

        if (token) {
            const payload = parseTokenPayload(token);
            tokenRole = typeof payload?.role === 'string' ? payload.role : null;
        }

        const rawUser = localStorage.getItem('user');
        if (rawUser) {
            try {
                const parsedUser = JSON.parse(rawUser) as UserContext;
                cachedRole = parsedUser?.role ?? null;
            } catch {
                cachedRole = null;
            }
        }

        if (!cachedRole && !tokenRole) {
            return <Navigate to="/login" replace />;
        }

        const hasAllowedRole =
            (cachedRole ? allowedRoles.includes(cachedRole) : false)
            || (tokenRole ? allowedRoles.includes(tokenRole) : false);

        if (!hasAllowedRole) {
            return <Navigate to="/hub" replace />;
        }
    }

    return <Outlet context={parentContext} />;
}
