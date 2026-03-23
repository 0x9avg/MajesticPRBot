import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setAccessToken } from '../../api/client';

const navigateMock = vi.fn();

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
    return {
        ...actual,
        useNavigate: () => navigateMock,
        Outlet: () => <div>Outlet Content</div>,
    };
});

import MainLayout from '../MainLayout';

const baseUser = {
    id: 1,
    discord_id: '1001',
    username: 'tester',
    nickname: 'Tester',
    role: 'manager',
    require_password_change: false,
    permissions: { 'admin.users.create': true },
};

describe('MainLayout', () => {
    beforeEach(() => {
        localStorage.clear();
        setAccessToken(null);
        navigateMock.mockReset();
    });

    it('loads user from network and logs out locally', async () => {
        setAccessToken('good-token');
        const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
            const url = String(input);

            if (url.endsWith('/api/auth/me')) {
                return new Response(JSON.stringify(baseUser), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                });
            }

            if (url.endsWith('/api/assistants/1001')) {
                return new Response(JSON.stringify({
                    status: 'success',
                    data: {
                        nickname: 'Tester',
                        role: 'manager',
                    },
                }), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                });
            }

            if (url.endsWith('/api/auth/logout/current')) {
                return new Response('{}', {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                });
            }

            return new Response('{}', { status: 404 });
        });
        vi.stubGlobal('fetch', fetchMock);

        render(<MainLayout />);

        await waitFor(() => {
            expect(screen.getByText('Tester')).toBeInTheDocument();
            expect(screen.getByText('manager')).toBeInTheDocument();
            expect(screen.getByText('Outlet Content')).toBeInTheDocument();
        });

        expect(fetchMock).not.toHaveBeenCalledWith(
            '/api/assistants/1001',
            expect.anything(),
        );

        const ui = userEvent.setup();
        await ui.click(screen.getByTitle('Выйти'));

        expect(localStorage.getItem('refresh_token')).toBeNull();
        expect(localStorage.getItem('user')).toBeNull();
        expect(navigateMock).toHaveBeenCalledWith('/login', { replace: true });
    });

    it('clears auth and redirects when /auth/me responds 401', async () => {
        setAccessToken('bad-token');
        localStorage.setItem('refresh_token', 'refresh-token');

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ detail: 'unauthorized' }), {
                status: 401,
                headers: { 'Content-Type': 'application/json' },
            })
        );
        vi.stubGlobal('fetch', fetchMock);

        render(<MainLayout />);

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalled();
            expect(navigateMock).toHaveBeenCalledWith('/login', { replace: true });
        });

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/auth/me',
            expect.objectContaining({
                headers: expect.any(Headers),
                credentials: 'include',
            })
        );

        expect(localStorage.getItem('refresh_token')).toBeNull();
        expect(localStorage.getItem('user')).toBeNull();
    });

    it('redirects to maintenance on 503 SITE_MAINTENANCE without logging out', async () => {
        setAccessToken('maintenance-token');
        localStorage.setItem('refresh_token', 'refresh-token');
        localStorage.setItem('user', '{"username":"tester"}');

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({
                detail: {
                    code: 'SITE_MAINTENANCE',
                    message: 'На сайте идут технические работы',
                },
            }), {
                status: 503,
                headers: { 'Content-Type': 'application/json' },
            })
        );
        vi.stubGlobal('fetch', fetchMock);

        render(<MainLayout />);

        await waitFor(() => {
            expect(navigateMock).toHaveBeenCalledWith('/maintenance', {
                replace: true,
                state: { message: 'На сайте идут технические работы' },
            });
        });

        expect(localStorage.getItem('refresh_token')).toBe('refresh-token');
        expect(localStorage.getItem('user')).toBe('{"username":"tester"}');
    });
});
