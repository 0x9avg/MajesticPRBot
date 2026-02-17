import { Navigate, Outlet, useOutletContext } from 'react-router-dom';
import type { UserContext } from '../types/auth';

interface ProtectedRouteProps {
    allowedRoles?: string[];
}

function getRoleFromToken(token: string): string | null {
    try {
        const parts = token.split('.');
        if (parts.length < 2) return null;

        const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
        const padded = b64.padEnd(b64.length + ((4 - (b64.length % 4)) % 4), '=');
        const decode = typeof atob === 'function' ? atob : null;
        if (!decode) return null;

        const payload = JSON.parse(decode(padded)) as { role?: unknown };
        return typeof payload.role === 'string' ? payload.role : null;
    } catch {
        return null;
    }
}

export default function ProtectedRoute({ allowedRoles }: ProtectedRouteProps) {
    const parentContext = useOutletContext<unknown>();
    const token = localStorage.getItem('access_token');

    if (!token) {
        return <Navigate to="/login" replace />;
    }

    if (allowedRoles && allowedRoles.length > 0) {
        // Read role from both cached user and token.
        // Cache may be fresher (from /auth/me), token may be the only source on cold start.
        let cachedRole: string | null = null;
        let tokenRole: string | null = getRoleFromToken(token);

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
