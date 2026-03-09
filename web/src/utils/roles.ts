import type { KnownRole } from '../types/auth';

export type Role = KnownRole;

export const ROLE_RANK: Record<Role, number> = {
    junior_employee: 0,
    employee: 1,
    senior_employee: 2,
    manager: 3,
    developer: 4,
};

export const ROLE_LABELS: Record<Role, string> = {
    junior_employee: 'Младший ассистент',
    employee: 'Ассистент',
    senior_employee: 'Старший ассистент',
    manager: 'Глава ассистентов',
    developer: 'Разработчик',
};

export const ALL_ROLES = Object.keys(ROLE_RANK) as Role[];

export const getAllowedRoles = (userRole?: Role | string): Role[] => {
    if (!userRole || ROLE_RANK[userRole as Role] === undefined) {
        return [];
    }

    if (userRole === 'developer') {
        return ALL_ROLES;
    }

    const creatorRank = ROLE_RANK[userRole as Role];
    return ALL_ROLES.filter((role) => ROLE_RANK[role] < creatorRank);
};
