import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const navigateMock = vi.fn();

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
    return {
        ...actual,
        useNavigate: () => navigateMock,
    };
});

import Login from '../Login';

describe('Login', () => {
    beforeEach(() => {
        localStorage.clear();
        navigateMock.mockReset();
    });

    it('logs in successfully, stores tokens and navigates to hub', async () => {
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({ access_token: 'access-1', refresh_token: 'refresh-1' }),
                    { status: 200, headers: { 'Content-Type': 'application/json' } }
                )
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        id: 1,
                        discord_id: '1001',
                        username: 'tester',
                        nickname: 'Tester',
                        role: 'manager',
                        require_password_change: false,
                        permissions: { can_register_users: true },
                    }),
                    { status: 200, headers: { 'Content-Type': 'application/json' } }
                )
            );

        vi.stubGlobal('fetch', fetchMock);

        const ui = userEvent.setup();
        render(<Login />);

        await ui.type(screen.getByPlaceholderText('Введите логин...'), 'tester');
        await ui.type(screen.getByPlaceholderText('••••••••'), 'secret');
        await ui.click(screen.getByRole('button', { name: 'Войти в систему' }));

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalledTimes(2);
            expect(navigateMock).toHaveBeenCalledWith('/hub');
        });

        expect(localStorage.getItem('access_token')).toBe('access-1');
        expect(localStorage.getItem('refresh_token')).toBe('refresh-1');
        expect(localStorage.getItem('user')).toContain('tester');
    });

    it('shows backend error on failed login', async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({ detail: 'Неверный логин или пароль' }),
                { status: 401, headers: { 'Content-Type': 'application/json' } }
            )
        );
        vi.stubGlobal('fetch', fetchMock);

        const ui = userEvent.setup();
        render(<Login />);

        await ui.type(screen.getByPlaceholderText('Введите логин...'), 'tester');
        await ui.type(screen.getByPlaceholderText('••••••••'), 'wrong');
        await ui.click(screen.getByRole('button', { name: 'Войти в систему' }));

        await waitFor(() => {
            expect(screen.getByText('Неверный логин или пароль')).toBeInTheDocument();
        });
        expect(navigateMock).not.toHaveBeenCalled();
    });

    it('clears auth and shows session message when /auth/me returns 401', async () => {
        localStorage.setItem('access_token', 'old-access');
        localStorage.setItem('refresh_token', 'old-refresh');
        localStorage.setItem('user', '{"username":"old"}');

        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({ access_token: 'access-2', refresh_token: 'refresh-2' }),
                    { status: 200, headers: { 'Content-Type': 'application/json' } }
                )
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({ detail: 'unauthorized' }),
                    { status: 401, headers: { 'Content-Type': 'application/json' } }
                )
            );

        vi.stubGlobal('fetch', fetchMock);

        const ui = userEvent.setup();
        render(<Login />);

        await ui.type(screen.getByPlaceholderText('Введите логин...'), 'tester');
        await ui.type(screen.getByPlaceholderText('••••••••'), 'secret');
        await ui.click(screen.getByRole('button', { name: 'Войти в систему' }));

        await waitFor(() => {
            expect(screen.getByText('Сессия недействительна. Выполните вход снова.')).toBeInTheDocument();
        });

        expect(localStorage.getItem('access_token')).toBeNull();
        expect(localStorage.getItem('refresh_token')).toBeNull();
        expect(localStorage.getItem('user')).toBeNull();
        expect(navigateMock).not.toHaveBeenCalled();
    });
});
