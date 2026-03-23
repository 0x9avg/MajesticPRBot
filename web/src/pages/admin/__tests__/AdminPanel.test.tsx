import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { UserContext } from '../../../types/auth';

let mockedUser: UserContext | null = null;

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
    return {
        ...actual,
        useOutletContext: () => ({ user: mockedUser }),
    };
});

vi.mock('../components/UserRegistration', () => ({ default: () => <div>UserRegistration</div> }));
vi.mock('../components/MediaRegistration', () => ({ default: () => <div>MediaRegistration</div> }));
vi.mock('../components/CreateEvent', () => ({ default: () => <div>CreateEvent</div> }));
vi.mock('../components/SiteManagement', () => ({ default: () => <div>GameServersManagement</div> }));
vi.mock('../components/RbacManagement', () => ({ default: () => <div>RbacManagement</div> }));
vi.mock('../components/SiteMaintenanceManagement', () => ({ default: () => <div>SiteMaintenanceManagement</div> }));
vi.mock('../components/SystemInfo', () => ({ default: () => <div>SystemInfo</div> }));
vi.mock('../components/AssistantsManagement', () => ({ default: () => <div>AssistantsManagement</div> }));
vi.mock('../components/PendingRequests', () => ({ default: () => <div>PendingRequests</div> }));
vi.mock('../components/SanctionsQueueManagement', () => ({ default: () => <div>SanctionsQueueManagement</div> }));
vi.mock('../../../config/app', () => ({ APP_VERSION: 'test-version' }));

import AdminPanel from '../AdminPanel';

describe('AdminPanel', () => {
    it('does not render weekly stats as an admin tab anymore', () => {
        mockedUser = {
            id: '1',
            discord_id: '1001',
            username: 'manager',
            nickname: 'Manager',
            role: 'manager',
            require_password_change: false,
            permissions: {
                'admin.panel.view': true,
                'assistants.view': true,
            },
        };

        render(<AdminPanel />);

        expect(screen.getByRole('button', { name: 'Ассистенты' })).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Недельная статистика' })).not.toBeInTheDocument();
        expect(screen.getByText('AssistantsManagement')).toBeInTheDocument();
    });

    it('renders split admin tabs for RBAC and maintenance surfaces', async () => {
        mockedUser = {
            id: '7',
            discord_id: '7001',
            username: 'developer',
            nickname: 'Developer',
            role: 'developer',
            require_password_change: false,
            permissions: {
                'admin.panel.view': true,
                'game_servers.settings.view': true,
                'rbac.view': true,
                'site.maintenance.view': true,
            },
        };

        const ui = userEvent.setup();
        render(<AdminPanel />);

        expect(screen.getByRole('button', { name: 'Игровые сервера' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'RBAC' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Тех. работы' })).toBeInTheDocument();
        expect(screen.getByText('GameServersManagement')).toBeInTheDocument();

        await ui.click(screen.getByRole('button', { name: 'RBAC' }));

        expect(screen.getByText('RbacManagement')).toBeInTheDocument();

        await ui.click(screen.getByRole('button', { name: 'Тех. работы' }));

        expect(screen.getByText('SiteMaintenanceManagement')).toBeInTheDocument();
    });
});
