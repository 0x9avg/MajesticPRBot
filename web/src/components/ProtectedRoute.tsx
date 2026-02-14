import { Navigate, Outlet } from 'react-router-dom';
import type { UserContext } from '../types/auth';

interface ProtectedRouteProps {
    allowedRoles?: string[];
}

export default function ProtectedRoute({ allowedRoles }: ProtectedRouteProps) {
    const token = localStorage.getItem('access_token');

    if (!token) {
        return <Navigate to="/login" replace />;
    }

    if (allowedRoles && allowedRoles.length > 0) {
        const rawUser = localStorage.getItem('user');
        if (!rawUser) {
            return <Navigate to="/login" replace />;
        }

        let parsedUser: UserContext | null = null;
        try {
            parsedUser = JSON.parse(rawUser) as UserContext;
        } catch {
            parsedUser = null;
        }

        if (!parsedUser) {
            return <Navigate to="/login" replace />;
        }

        if (!allowedRoles.includes(parsedUser.role)) {
            return <Navigate to="/hub" replace />;
        }
    }

    return <Outlet />;
}
