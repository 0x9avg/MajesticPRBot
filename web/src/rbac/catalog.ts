import type { PermissionKey } from './guards';

export interface AdminTabDefinition {
    id: 'events' | 'users' | 'media' | 'requests' | 'assistants' | 'sanctions' | 'guild' | 'system';
    label: string;
    requireAny: PermissionKey[];
}

export const ADMIN_TABS: AdminTabDefinition[] = [
    { id: 'events', label: 'Мероприятия', requireAny: ['events.create'] },
    { id: 'users', label: 'Пользователи', requireAny: ['admin.users.create'] },
    { id: 'media', label: 'Медиа', requireAny: ['streamers.create'] },
    { id: 'requests', label: 'Запросы', requireAny: ['events.spec.manage'] },
    {
        id: 'assistants',
        label: 'Ассистенты',
        requireAny: [
            'assistants.sessions.manage',
            'assistants.points.manage',
            'assistants.sanctions.manage',
            'assistants.warnings.manage',
        ],
    },
    {
        id: 'sanctions',
        label: 'Санкции',
        requireAny: ['assistants.sanctions.manage'],
    },
    { id: 'guild', label: 'Сервер', requireAny: ['guild.settings.update', 'guild.templates.update', 'guild.rates.update'] },
    { id: 'system', label: 'Система', requireAny: ['monitoring.view'] },
];

export const ADMIN_SECTION_PERMISSIONS: PermissionKey[] = ADMIN_TABS.flatMap((tab) => tab.requireAny);
