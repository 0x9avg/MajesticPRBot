import type { UserContext } from '../types/auth';

export type PermissionKey = string;

function getPermissions(user: UserContext | null | undefined): Record<string, boolean | undefined> {
    return (user?.permissions ?? {}) as Record<string, boolean | undefined>;
}

export function hasPerm(user: UserContext | null | undefined, permission: PermissionKey): boolean {
    return getPermissions(user)[permission] === true;
}

export function hasAny(user: UserContext | null | undefined, permissions: PermissionKey[]): boolean {
    if (permissions.length === 0) return true;
    const map = getPermissions(user);
    return permissions.some((permission) => map[permission] === true);
}

export function hasAll(user: UserContext | null | undefined, permissions: PermissionKey[]): boolean {
    if (permissions.length === 0) return true;
    const map = getPermissions(user);
    return permissions.every((permission) => map[permission] === true);
}
