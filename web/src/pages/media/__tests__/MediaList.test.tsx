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

import MediaList from '../MediaList';

const makeUser = (role: UserContext['role']): UserContext => ({
    id: 1,
    discord_id: '1001',
    username: 'tester',
    nickname: 'Tester',
    role,
    require_password_change: false,
    permissions: {},
});

const makeJsonResponse = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });

describe('MediaList', () => {
    beforeEach(() => {
        navigateMock.mockReset();
        mockedUser = makeUser('employee');
    });

    it('renders empty activities state', async () => {
        const fetchMock = vi.fn((input: string | URL | Request) => {
            const url = typeof input === 'string' ? input : input.toString();
            if (url.includes('/api/streamers?online_only=true')) {
                return Promise.resolve(makeJsonResponse({ status: 'success', data: { streamers: [] } }));
            }
            if (url.endsWith('/api/streamers')) {
                return Promise.resolve(makeJsonResponse({ status: 'success', data: { streamers: [] } }));
            }
            if (url.includes('/api/events/active')) {
                return Promise.resolve(makeJsonResponse({ status: 'success', data: [] }));
            }
            return Promise.resolve(makeJsonResponse({}, 404));
        });

        vi.stubGlobal('fetch', fetchMock);

        render(<MediaList />);

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalled();
            expect(screen.getByText('Нет активностей')).toBeInTheDocument();
        });
    });

    it('navigates to participant profile from event card', async () => {
        const fetchMock = vi.fn((input: string | URL | Request) => {
            const url = typeof input === 'string' ? input : input.toString();
            if (url.includes('/api/streamers?online_only=true')) {
                return Promise.resolve(makeJsonResponse({ status: 'success', data: { streamers: [] } }));
            }
            if (url.endsWith('/api/streamers')) {
                return Promise.resolve(makeJsonResponse({ status: 'success', data: { streamers: [] } }));
            }
            if (url.includes('/api/events/active')) {
                return Promise.resolve(
                    makeJsonResponse({
                        status: 'success',
                        data: [
                            {
                                id: 101,
                                name: 'Night Event',
                                description: 'Desc',
                                priority: 2,
                                is_pinned: false,
                                participants: [{ pr_id: 42, nickname: 'Nick' }],
                                current_participants: 1,
                                required_pr_count: 2,
                                pr_slots: 2,
                            },
                        ],
                    })
                );
            }
            return Promise.resolve(makeJsonResponse({}, 404));
        });

        vi.stubGlobal('fetch', fetchMock);

        const ui = userEvent.setup();
        render(<MediaList />);

        await waitFor(() => {
            expect(screen.getByText('Night Event')).toBeInTheDocument();
            expect(screen.getByText('@Nick')).toBeInTheDocument();
        });

        await ui.click(screen.getByText('@Nick'));
        expect(navigateMock).toHaveBeenCalledWith('/profile/42');
    });
});
