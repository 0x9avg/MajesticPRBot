import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { PermissionKey } from '../../../rbac/guards';
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

const makeUser = (role: UserContext['role'], permissions: Partial<Record<PermissionKey, boolean>> = {}): UserContext => ({
    id: 1,
    discord_id: '1001',
    username: 'tester',
    nickname: 'Tester',
    role,
    require_password_change: false,
    permissions: {
        'returns.queue.view': true,
        'returns.history.view': true,
        'complaints.queue.view': true,
        'complaints.history.view': true,
        'removals.queue.view': true,
        'removals.history.view': true,
        ...(role === 'manager' || role === 'developer'
            ? {
                'admin.panel.view': true,
                'admin.users.create': true,
                'assistants.weekly.manage': true,
                'assistants.view': true,
                'events.view': true,
                'events.create': true,
                'media.view': true,
                'media.create': true,
                'media.update': true,
                'media.delete': true,
            }
            : {}),
        ...(role === 'developer'
            ? {
                'monitoring.view': true
            }
            : {}),
        ...permissions,
    },
});

const createFetchMock = ({
    streamers = [
        {
            streamer_id: 'streamer-1',
            streamer_name: 'Alpha',
            priority: 2,
            pr_slots: 2,
            assignments: [{ pr_id: '2002', nickname: 'Helper' }],
        },
    ],
    events = [],
    returnsQueue = [],
}: {
    streamers?: unknown[];
    events?: unknown[];
    returnsQueue?: unknown[];
} = {}) => {
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
                        streamers,
                    },
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } }
            );
        }

        if (url.includes('/api/events/active')) {
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: events,
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } }
            );
        }

        if (url.includes('/api/returns/queue')) {
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: returnsQueue,
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
        await waitFor(() => {
            expect(screen.getByText('Bot Dashboard')).toBeInTheDocument();
        });

        mockedUser = makeUser('employee');
        rerender(<MainHub />);

        await waitFor(() => {
            expect(screen.queryByText('Админ-панель')).not.toBeInTheDocument();
            expect(screen.queryByText('Bot Dashboard')).not.toBeInTheDocument();
        });
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

        await ui.click(screen.getByText('Жалобы'));
        expect(navigateMock).toHaveBeenCalledWith('/complaints');

        await ui.click(screen.getByText('Снятие наказаний'));
        expect(navigateMock).toHaveBeenCalledWith('/removals');
    });

    it('shows weekly management card in Управление and navigates to the full-screen page', async () => {
        createFetchMock();
        mockedUser = makeUser('employee', { 'assistants.weekly.manage': true });

        const ui = userEvent.setup();
        render(<MainHub />);

        await waitFor(() => {
            expect(screen.getByText('Недельная статистика')).toBeInTheDocument();
        });

        expect(screen.queryByText('Админ-панель')).not.toBeInTheDocument();

        await ui.click(screen.getByText('Недельная статистика'));
        expect(navigateMock).toHaveBeenCalledWith('/assistants/weekly/manage');
    });

    it('hides media menu card without media.view permission', async () => {
        createFetchMock();
        mockedUser = makeUser('employee', {
            'media.view': false,
            'assistants.view': true,
        });

        render(<MainHub />);

        await waitFor(() => {
            expect(screen.queryByText('Медиа')).not.toBeInTheDocument();
        });
    });

    it('renders event and streamer controls per exact permissions', async () => {
        createFetchMock({
            events: [
                {
                    id: 55,
                    name: 'Event Alpha',
                    description: 'Test event',
                    priority: 2,
                    is_pinned: false,
                    event_kind: 'event',
                    participants: [],
                },
            ],
            streamers: [
                {
                    streamer_id: 'streamer-7',
                    streamer_name: 'Bravo',
                    priority: 2,
                    pr_slots: 2,
                    assignments: [],
                },
            ],
        });
        mockedUser = makeUser('employee', {
            'media.view': true,
            'media.update': false,
            'media.delete': true,
            'events.view': true,
            'events.update': true,
            'events.runtime.manage': false,
        });

        render(<MainHub />);

        await waitFor(() => {
            expect(screen.getByText('Event Alpha')).toBeInTheDocument();
            expect(screen.getByText('Bravo')).toBeInTheDocument();
        });

        expect(screen.getByTitle('Настройки события')).toBeInTheDocument();
        expect(screen.queryByTitle('Завершить событие')).not.toBeInTheDocument();
        expect(screen.queryByTitle('Временные настройки')).not.toBeInTheDocument();
        expect(screen.getByTitle('Удалить стримера')).toBeInTheDocument();
    });

    it('shows ready returns badge when queue has claimable items', async () => {
        createFetchMock({
            returnsQueue: [
                { id: '1', can_claim: true },
                { id: '2', can_claim: false },
                { id: '3', can_claim: true },
            ],
        });

        render(<MainHub />);

        await waitFor(() => {
            expect(screen.getByTestId('menu-badge-returns')).toHaveTextContent('2');
        });
    });

    it('does not render raw 0 when queue has no claimable returns', async () => {
        createFetchMock({
            returnsQueue: [
                { id: '1', can_claim: false },
                { id: '2', can_claim: false },
            ],
        });

        render(<MainHub />);

        await waitFor(() => {
            expect(screen.getByText('Возвраты')).toBeInTheDocument();
        });

        expect(screen.queryByTestId('menu-badge-returns')).not.toBeInTheDocument();
        expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();
    });
});
