import type { ReactNode } from 'react';
import { hasAll, hasAny, type PermissionKey } from '../../rbac/guards';
import type { UserContext } from '../../types/auth';

interface PermissionGateProps {
    user: UserContext | null | undefined;
    requireAny?: PermissionKey[];
    requireAll?: PermissionKey[];
    fallback?: ReactNode;
    children: ReactNode;
}

export default function PermissionGate({
    user,
    requireAny = [],
    requireAll = [],
    fallback = null,
    children,
}: PermissionGateProps) {
    const anyAllowed = requireAny.length === 0 || hasAny(user, requireAny);
    const allAllowed = requireAll.length === 0 || hasAll(user, requireAll);
    if (!anyAllowed || !allAllowed) {
        return <>{fallback}</>;
    }
    return <>{children}</>;
}
