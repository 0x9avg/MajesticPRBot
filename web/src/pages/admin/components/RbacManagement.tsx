import React from 'react';
import { AlertCircle, RefreshCw, Save, Settings2 } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';

import { apiFetch } from '../../../api/client';
import NotificationToast from '../../../components/feedback/NotificationToast';
import { usePopupToast } from '../../../components/feedback/hooks';
import { hasPerm } from '../../../rbac/guards';
import { getApiErrorMessage, unwrapApiData } from '../../../types/api';
import type { OutletUserContext } from '../../../types/auth';
import type { PermissionImplications } from '../../../types/domain';
import { ROLE_LABELS } from '../../../utils/roles';

type PermissionMatrix = Record<string, Record<string, boolean>>;

interface RbacSnapshot {
    roles: string[];
    permissions: string[];
    matrix: PermissionMatrix;
    permission_implications: PermissionImplications;
}

const RBAC_ENDPOINT = '/api/admin/rbac';

const normalizeBoolean = (value: unknown) => value === true;

const normalizeMatrix = (
    rawMatrix: unknown,
    roles: string[],
    permissions: string[],
): PermissionMatrix => {
    const matrix: PermissionMatrix = {};
    const source = rawMatrix && typeof rawMatrix === 'object' && !Array.isArray(rawMatrix)
        ? rawMatrix as Record<string, unknown>
        : {};

    roles.forEach((role) => {
        const rawRolePermissions = source[role];
        const roleSource = rawRolePermissions && typeof rawRolePermissions === 'object' && !Array.isArray(rawRolePermissions)
            ? rawRolePermissions as Record<string, unknown>
            : {};
        matrix[role] = Object.fromEntries(
            permissions.map((permission) => [permission, normalizeBoolean(roleSource[permission])]),
        );
    });

    return matrix;
};

const normalizeRbacSnapshot = (payload: unknown): RbacSnapshot => {
    const data = unwrapApiData<unknown>(payload);
    const raw = data && typeof data === 'object' && !Array.isArray(data)
        ? data as Record<string, unknown>
        : {};
    const roles = Array.isArray(raw.roles) ? raw.roles.map((role) => String(role)) : [];
    const permissions = Array.isArray(raw.permissions)
        ? raw.permissions.map((permission) => String(permission))
        : [];
    const permissionImplications = raw.permission_implications && typeof raw.permission_implications === 'object' && !Array.isArray(raw.permission_implications)
        ? Object.fromEntries(
            Object.entries(raw.permission_implications as Record<string, unknown>).map(([permission, implied]) => [
                permission,
                Array.isArray(implied) ? implied.map((value) => String(value)) : [],
            ]),
        ) as PermissionImplications
        : {};

    return {
        roles,
        permissions,
        matrix: normalizeMatrix(raw.matrix, roles, permissions),
        permission_implications: permissionImplications,
    };
};

const applyPermissionImplications = (
    sourceMatrix: PermissionMatrix,
    roles: string[],
    permissions: string[],
    implications: PermissionImplications,
): PermissionMatrix => {
    const nextMatrix = normalizeMatrix(sourceMatrix, roles, permissions);
    let changed = true;

    while (changed) {
        changed = false;
        roles.forEach((role) => {
            permissions.forEach((permission) => {
                if (nextMatrix[role]?.[permission] !== true) return;
                (implications[permission] ?? []).forEach((impliedPermission) => {
                    if (nextMatrix[role]?.[impliedPermission] === true) return;
                    if (!nextMatrix[role]) {
                        nextMatrix[role] = {};
                    }
                    nextMatrix[role][impliedPermission] = true;
                    changed = true;
                });
            });
        });
    }

    return nextMatrix;
};

const isPermissionDerived = (
    matrix: PermissionMatrix,
    role: string,
    permission: string,
    implications: PermissionImplications,
): boolean => Object.entries(implications).some(([sourcePermission, impliedPermissions]) => (
    sourcePermission !== permission
    && matrix[role]?.[sourcePermission] === true
    && impliedPermissions.includes(permission)
));

const formatRoleLabel = (role: string) => ROLE_LABELS[role as keyof typeof ROLE_LABELS] ?? role;

const formatPermissionLabel = (permission: string) => permission;

const RbacManagement = () => {
    const { user } = useOutletContext<OutletUserContext>();
    const { toast, showToast, closeToast } = usePopupToast(3200);
    const canViewRbac = hasPerm(user, 'rbac.view') || hasPerm(user, 'rbac.update');
    const canUpdateRbac = hasPerm(user, 'rbac.update');

    const [loading, setLoading] = React.useState(true);
    const [saving, setSaving] = React.useState(false);
    const [error, setError] = React.useState<string | null>(null);
    const [roles, setRoles] = React.useState<string[]>([]);
    const [permissions, setPermissions] = React.useState<string[]>([]);
    const [matrix, setMatrix] = React.useState<PermissionMatrix>({});
    const [permissionImplications, setPermissionImplications] = React.useState<PermissionImplications>({});

    const loadRbac = React.useCallback(async () => {
        setLoading(true);
        setError(null);

        try {
            const response = await apiFetch(RBAC_ENDPOINT);
            const data = await response.json().catch(() => ({} as unknown));
            if (!response.ok) {
                throw new Error(getApiErrorMessage(data, 'Не удалось загрузить матрицу RBAC'));
            }

            const snapshot = normalizeRbacSnapshot(data);
            setRoles(snapshot.roles);
            setPermissions(snapshot.permissions);
            setMatrix(snapshot.matrix);
            setPermissionImplications(snapshot.permission_implications);
        } catch (loadError: unknown) {
            const message = loadError instanceof Error ? loadError.message : 'Не удалось загрузить матрицу RBAC';
            setError(message);
            showToast(message, 'error');
        } finally {
            setLoading(false);
        }
    }, [showToast]);

    React.useEffect(() => {
        void loadRbac();
    }, [loadRbac]);

    const togglePermission = (role: string, permission: string) => {
        if (!canUpdateRbac) return;
        setMatrix((current) => {
            const next = {
                ...current,
                [role]: {
                    ...(current[role] ?? {}),
                    [permission]: !(current[role]?.[permission] ?? false),
                },
            };

            return applyPermissionImplications(next, roles, permissions, permissionImplications);
        });
    };

    const handleSave = async () => {
        if (!canUpdateRbac) return;
        setSaving(true);
        setError(null);

        try {
            const response = await apiFetch(RBAC_ENDPOINT, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ matrix }),
            });
            const data = await response.json().catch(() => ({} as unknown));
            if (!response.ok) {
                throw new Error(getApiErrorMessage(data, 'Не удалось сохранить матрицу RBAC'));
            }

            const snapshot = normalizeRbacSnapshot(data);
            setRoles(snapshot.roles);
            setPermissions(snapshot.permissions);
            setMatrix(snapshot.matrix);
            setPermissionImplications(snapshot.permission_implications);
            showToast('Матрица RBAC обновлена');
        } catch (saveError: unknown) {
            const message = saveError instanceof Error ? saveError.message : 'Не удалось сохранить матрицу RBAC';
            setError(message);
            showToast(message, 'error');
        } finally {
            setSaving(false);
        }
    };

    if (!canViewRbac) {
        return (
            <div className="space-y-6 animate-[fadeIn_0.3s_ease-in-out]">
                <div className="flex items-center gap-4 border-b border-white/10 pb-6">
                    <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-sky-500/30 bg-sky-500/15 text-sky-100">
                        <Settings2 className="h-6 w-6" />
                    </div>
                    <div>
                        <h2 className="text-2xl font-bold text-white">RBAC</h2>
                        <p className="text-white/60">Матрица прав доступа для staff-ролей.</p>
                    </div>
                </div>
                <div className="rounded-2xl border border-white/5 bg-[#1e1e1e] p-8 text-center text-white/45">
                    Недостаточно прав для просмотра RBAC.
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-6 animate-[fadeIn_0.3s_ease-in-out]">
            <div className="flex flex-col gap-4 border-b border-white/10 pb-6">
                <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-4">
                        <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-sky-500/30 bg-sky-500/15 text-sky-100">
                            <Settings2 className="h-6 w-6" />
                        </div>
                        <div>
                            <h2 className="text-2xl font-bold text-white">RBAC</h2>
                            <p className="text-white/60">Матрица прав доступа для staff-ролей.</p>
                        </div>
                    </div>

                    <button
                        type="button"
                        onClick={() => void loadRbac()}
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
                <div className="rounded-2xl border border-white/5 bg-[#1e1e1e] overflow-hidden">
                    <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/5 px-5 py-4">
                        <div>
                            <div className="text-sm font-semibold text-white">Матрица прав доступа</div>
                            <div className="text-xs text-white/45">Implied permissions включаются автоматически и не редактируются в противоречивом состоянии.</div>
                        </div>
                        <button
                            type="button"
                            onClick={() => void handleSave()}
                            disabled={saving || !canUpdateRbac}
                            className="inline-flex items-center justify-center gap-2 rounded-xl border border-sky-500/20 bg-sky-500/15 px-4 py-2.5 text-sm font-medium text-sky-100 transition hover:bg-sky-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {saving ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                            Сохранить матрицу
                        </button>
                    </div>

                    <div className="overflow-x-auto">
                        <table className="min-w-full text-sm">
                            <thead className="bg-[#242424] text-left text-xs uppercase tracking-[0.16em] text-white/40">
                                <tr>
                                    <th className="sticky left-0 z-10 bg-[#242424] px-4 py-3">Permission</th>
                                    {roles.map((role) => (
                                        <th key={role} className="px-4 py-3 text-center">
                                            {formatRoleLabel(role)}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-white/5">
                                {permissions.map((permission) => (
                                    <tr key={permission} className="hover:bg-white/[0.02]">
                                        <td className="sticky left-0 z-10 bg-[#1e1e1e] px-4 py-3 font-mono text-xs text-white/75">
                                            {formatPermissionLabel(permission)}
                                        </td>
                                        {roles.map((role) => {
                                            const checked = matrix[role]?.[permission] === true;
                                            const derived = isPermissionDerived(matrix, role, permission, permissionImplications);
                                            return (
                                                <td key={`${role}-${permission}`} className="px-4 py-3 text-center">
                                                    <label className="inline-flex cursor-pointer items-center justify-center">
                                                        <input
                                                            data-testid={`rbac-cell-${role}-${permission}`}
                                                            type="checkbox"
                                                            checked={checked}
                                                            onChange={() => togglePermission(role, permission)}
                                                            disabled={!canUpdateRbac || derived}
                                                            className="h-4 w-4 rounded border-white/20 bg-black/20 text-sky-500 focus:ring-sky-500/40"
                                                        />
                                                    </label>
                                                </td>
                                            );
                                        })}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
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

export default RbacManagement;
