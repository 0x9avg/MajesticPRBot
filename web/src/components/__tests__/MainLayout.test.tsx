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
    permissions: { can_register_users: true },
};

describe('MainLayout', () => {
    beforeEach(() => {
        localStorage.clear();
        navigateMock.mockReset();
    });

    it('loads cached user and logs out locally when token is absent', async () => {
        localStorage.setItem('user', JSON.stringify(baseUser));

        render(<MainLayout />);

        await waitFor(() => {
            expect(screen.getByText('Tester')).toBeInTheDocument();
            expect(screen.getByText('manager')).toBeInTheDocument();
            expect(screen.getByText('Outlet Content')).toBeInTheDocument();
        });

        const ui = userEvent.setup();
        await ui.click(screen.getByTitle('Выйти'));

        expect(localStorage.getItem('access_token')).toBeNull();
        expect(localStorage.getItem('refresh_token')).toBeNull();
        expect(localStorage.getItem('user')).toBeNull();
        expect(navigateMock).toHaveBeenCalledWith('/login', { replace: true });
    });

    it('clears auth and redirects when /auth/me responds 401', async () => {
        localStorage.setItem('access_token', 'bad-token');
        localStorage.setItem('refresh_token', 'refresh-token');
        localStorage.setItem('user', JSON.stringify(baseUser));

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ detail: 'unauthorized' }), {
                status: 401,
                headers: { 'Content-Type': 'application/json' },
            })
        );
        vi.stubGlobal('fetch', fetchMock);

        render(<MainLayout />);

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalledWith('/api/auth/me', {
                headers: { Authorization: 'Bearer bad-token' },
            });
            expect(navigateMock).toHaveBeenCalledWith('/login', { replace: true });
        });

        expect(localStorage.getItem('access_token')).toBeNull();
        expect(localStorage.getItem('refresh_token')).toBeNull();
        expect(localStorage.getItem('user')).toBeNull();
    });
});
