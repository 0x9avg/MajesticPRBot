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
    permissions: {
        'returns.view': true,
        'returns.history.view': true,
        ...(role === 'manager' || role === 'developer'
            ? {
                'admin.users.create': true,
                'events.create': true,
                'streamers.create': true,
                'streamers.update': true,
                'streamers.delete': true,
            }
            : {}),
        ...(role === 'developer'
            ? {
                'monitoring.view': true,
                'monitoring.refresh': true,
            }
            : {}),
    },
});

const createFetchMock = () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);

        if (url.includes('/api/stats/dashboard')) {
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: {
                        assigned_pr_count: 5,
                        unassigned_media_count: 2,
                        events_today_count: 1,
                    },
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } }
            );
        }

        if (url.includes('/api/streamers?online_only=true&gta_only=true')) {
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: {
                        streamers: [
                            {
                                streamer_id: 'streamer-1',
                                streamer_name: 'Alpha',
                                priority: 2,
                                pr_slots: 2,
                                assignments: [{ pr_id: '2002', nickname: 'Helper' }],
                            },
                        ],
                    },
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } }
            );
        }

        if (url.includes('/api/events/active')) {
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: [],
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } }
            );
        }

        return new Response('{}', { status: 404 });
    });

    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
};

describe('MainHub', () => {
    beforeEach(() => {
        navigateMock.mockReset();
        mockedUser = makeUser('manager');
    });

    it('loads and renders dashboard stats', async () => {
        const fetchMock = createFetchMock();

        render(<MainHub />);

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalled();
            expect(screen.getByText('Кол-во занятых PR').parentElement).toHaveTextContent('5');
            expect(screen.getByText('Стримеров в GTA').parentElement).toHaveTextContent('2');
            expect(screen.getByText('Требуется ассистентов').parentElement).toHaveTextContent('1');
        });
    });

    it('shows admin section for manager and hides it for employee', async () => {
        createFetchMock();

        const { rerender } = render(<MainHub />);

        await waitFor(() => {
            expect(screen.getByText('Админ-панель')).toBeInTheDocument();
        });
        expect(screen.queryByText('Bot Dashboard')).not.toBeInTheDocument();

        mockedUser = makeUser('developer');
        rerender(<MainHub />);
        expect(screen.getByText('Bot Dashboard')).toBeInTheDocument();

        mockedUser = makeUser('employee');
        rerender(<MainHub />);

        expect(screen.queryByText('Админ-панель')).not.toBeInTheDocument();
        expect(screen.queryByText('Bot Dashboard')).not.toBeInTheDocument();
    });

    it('navigates when menu cards are clicked', async () => {
        createFetchMock();

        const ui = userEvent.setup();
        render(<MainHub />);

        await ui.click(screen.getByText('Медиа'));
        expect(navigateMock).toHaveBeenCalledWith('/media');

        await ui.click(screen.getByText('Таблица PR Ассистентов'));
        expect(navigateMock).toHaveBeenCalledWith('/assistants');

        await ui.click(screen.getByText('Возвраты'));
        expect(navigateMock).toHaveBeenCalledWith('/returns');
    });
});
