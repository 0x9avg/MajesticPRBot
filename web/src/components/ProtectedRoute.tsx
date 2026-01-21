import { Navigate, Outlet } from 'react-router-dom';

interface ProtectedRouteProps {
    allowedRoles?: string[];
}

export default function ProtectedRoute({ allowedRoles }: ProtectedRouteProps) {
    const token = localStorage.getItem('access_token');

    if (!token) {
        return <Navigate to="/login" replace />;
    }

    return <Outlet />;
}
