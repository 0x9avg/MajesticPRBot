import React from 'react';
import { render, screen } from '@testing-library/react';
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
vi.mock('../components/SiteManagement', () => ({ default: () => <div>SiteManagement</div> }));
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
                'assistants.sessions.manage': true,
            },
        };

        render(<AdminPanel />);

        expect(screen.getByRole('button', { name: 'Ассистенты' })).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Недельная статистика' })).not.toBeInTheDocument();
        expect(screen.getByText('AssistantsManagement')).toBeInTheDocument();
    });
});
