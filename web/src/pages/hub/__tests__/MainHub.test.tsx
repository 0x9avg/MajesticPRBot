import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UserContext } from '../../../types/auth';

let mockedUser: UserContext | null = null;
const navigateMock = vi.fn();

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
    return {
        ...actual,
        useNavigate: () => navigateMock,
        useOutletContext: () => ({ user: mockedUser }),
    };
});

import MainHub from '../MainHub';

const makeUser = (role: UserContext['role']): UserContext => ({
    id: 1,
    discord_id: '1001',
    username: 'tester',
    nickname: 'Tester',
    role,
    require_password_change: false,
    permissions: { can_register_users: role === 'manager' || role === 'developer' },
});

const mockStatsResponse = () => {
    const fetchMock = vi.fn().mockResolvedValue(
        new Response(
            JSON.stringify({
                status: 'success',
                data: {
                    assigned_pr_count: 5,
                    unassigned_media_count: 2,
                    events_today_count: 1,
                },
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
        )
    );
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
};

describe('MainHub', () => {
    beforeEach(() => {
        navigateMock.mockReset();
        mockedUser = makeUser('manager');
    });

    it('loads and renders dashboard stats', async () => {
        const fetchMock = mockStatsResponse();

        render(<MainHub />);

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalledWith('/api/stats/dashboard');
            expect(screen.getByText('5')).toBeInTheDocument();
            expect(screen.getByText('2')).toBeInTheDocument();
            expect(screen.getByText('1')).toBeInTheDocument();
        });
    });

    it('shows admin section for manager and hides it for employee', async () => {
        mockStatsResponse();

        const { rerender } = render(<MainHub />);

        await waitFor(() => {
            expect(screen.getByText('Админ-панель')).toBeInTheDocument();
            expect(screen.getByText('Bot Dashboard')).toBeInTheDocument();
        });

        mockedUser = makeUser('employee');
        rerender(<MainHub />);

        expect(screen.queryByText('Админ-панель')).not.toBeInTheDocument();
        expect(screen.queryByText('Bot Dashboard')).not.toBeInTheDocument();
    });

    it('navigates when menu cards are clicked', async () => {
        mockStatsResponse();

        const ui = userEvent.setup();
        render(<MainHub />);

        await ui.click(screen.getByText('Медиа'));
        expect(navigateMock).toHaveBeenCalledWith('/media');

        await ui.click(screen.getByText('Таблица пиаров'));
        expect(navigateMock).toHaveBeenCalledWith('/pr-stats');
    });
});
