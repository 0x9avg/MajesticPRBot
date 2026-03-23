import type { PermissionKey } from './guards';

export interface AdminTabDefinition {
    id: 'events' | 'users' | 'media' | 'requests' | 'assistants' | 'sanctions' | 'game_servers' | 'rbac' | 'site_maintenance' | 'system';
    label: string;
    requireAny: PermissionKey[];
}

export const ADMIN_ASSISTANTS_TAB_PERMISSIONS: PermissionKey[] = [
    'assistants.view',
    'assistants.sessions.view',
    'assistants.sessions.manage',
    'assistants.points.update',
    'assistants.sanctions.manage',
    'assistants.warnings.manage',
    'admin.users.role.update',
    'admin.users.deactivate',
];

export const ADMIN_TABS: AdminTabDefinition[] = [
    { id: 'events', label: 'Мероприятия', requireAny: ['events.create'] },
    { id: 'users', label: 'Пользователи', requireAny: ['admin.users.create'] },
    { id: 'media', label: 'Медиа', requireAny: ['media.create'] },
    { id: 'requests', label: 'Запросы', requireAny: ['events.spec_requests.review'] },
    {
        id: 'assistants',
        label: 'Ассистенты',
        requireAny: ADMIN_ASSISTANTS_TAB_PERMISSIONS,
    },
    {
        id: 'sanctions',
        label: 'Санкции',
        requireAny: ['assistants.sanctions.manage'],
    },
    {
        id: 'game_servers',
        label: 'Игровые сервера',
        requireAny: [
            'game_servers.settings.view',
            'game_servers.settings.update',
            'game_servers.templates.view',
            'game_servers.templates.update',
            'game_servers.rates.view',
            'game_servers.rates.update',
        ],
    },
    { id: 'rbac', label: 'RBAC', requireAny: ['rbac.view', 'rbac.update'] },
    { id: 'site_maintenance', label: 'Тех. работы', requireAny: ['site.maintenance.view', 'site.maintenance.update'] },
    { id: 'system', label: 'Система', requireAny: ['monitoring.view'] },
];

export const ADMIN_SECTION_PERMISSIONS: PermissionKey[] = ['admin.panel.view'];
