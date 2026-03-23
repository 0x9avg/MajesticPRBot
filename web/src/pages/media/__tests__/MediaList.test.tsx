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

const makeUser = (
    role: UserContext['role'],
    permissions: Record<string, boolean> = {},
): UserContext => ({
    id: '1',
    discord_id: '1001',
    username: 'tester',
    nickname: 'Tester',
    role,
    require_password_change: false,
    permissions,
});

const makeJsonResponse = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });

describe('MediaList', () => {
    beforeEach(() => {
        navigateMock.mockReset();
        mockedUser = makeUser('employee', { 'media.view': true });
    });

    it('renders empty data state', async () => {
        const fetchMock = vi.fn((input: string | URL | Request) => {
            const url = typeof input === 'string' ? input : input.toString();
            if (url.endsWith('/api/streamers')) {
                return Promise.resolve(makeJsonResponse({ status: 'success', data: { streamers: [] } }));
            }
            return Promise.resolve(makeJsonResponse({}, 404));
        });

        vi.stubGlobal('fetch', fetchMock);

        render(<MediaList />);

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalled();
            expect(screen.getByText('Нет данных')).toBeInTheDocument();
        });
    });

    it('navigates to streamer profile', async () => {
        const fetchMock = vi.fn((input: string | URL | Request) => {
            const url = typeof input === 'string' ? input : input.toString();
            if (url.endsWith('/api/streamers')) {
                return Promise.resolve(
                    makeJsonResponse({
                        status: 'success',
                        data: [
                            {
                                streamer_id: 1,
                                streamer_name: 'alpha',
                                is_online: true,
                                priority: 1,
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
            expect(screen.getByText('alpha')).toBeInTheDocument();
        });

        const profileBtn = screen.getByTitle('Открыть профиль медиа');
        await ui.click(profileBtn);
        expect(navigateMock).toHaveBeenCalledWith('/media/1');
    });

    it('shows access denied state without media.view', async () => {
        mockedUser = makeUser('employee');
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);

        render(<MediaList />);

        await waitFor(() => {
            expect(screen.getByText('Недостаточно прав для просмотра медиа.')).toBeInTheDocument();
        });

        expect(fetchMock).not.toHaveBeenCalled();
    });
});
