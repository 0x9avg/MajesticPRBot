import React from 'react';
import { Navigate, useOutletContext } from 'react-router-dom';
import type { ReactNode } from 'react';
import type { OutletUserContext } from '../../types/auth';
import { hasAll, hasAny, type PermissionKey } from '../../rbac/guards';

void React;

interface PermissionRouteProps {
    requireAny?: PermissionKey[];
    requireAll?: PermissionKey[];
    fallbackPath?: string;
    children: ReactNode;
}

export default function PermissionRoute({
    requireAny = [],
    requireAll = [],
    fallbackPath = '/hub',
    children,
}: PermissionRouteProps) {
    const { user, authResolved = false } = useOutletContext<OutletUserContext>();

    if (!authResolved) {
        return (
            <div
                data-testid="permission-route-loading"
                className="text-sm text-white/60"
            >
                Проверка прав...
            </div>
        );
    }

    if (!user) {
        return <Navigate to={fallbackPath} replace />;
    }

    const allowedAny = requireAny.length === 0 || hasAny(user, requireAny);
    const allowedAll = requireAll.length === 0 || hasAll(user, requireAll);

    if (!allowedAny || !allowedAll) {
        return <Navigate to={fallbackPath} replace />;
    }

    return <>{children}</>;
}
