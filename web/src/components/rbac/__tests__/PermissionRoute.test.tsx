import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import PermissionRoute from '../PermissionRoute';
import type { UserContext } from '../../../types/auth';

function renderWithContext(
    user: UserContext | null,
    authResolved: boolean,
    initialPath: string
) {
    const Layout = () => <Outlet context={{ user, authResolved }} />;

    render(
        <MemoryRouter initialEntries={[initialPath]}>
            <Routes>
                <Route path="/hub" element={<div>Hub Page</div>} />
                <Route element={<Layout />}>
                    <Route
                        path="/admin"
                        element={
                            <PermissionRoute requireAny={['events.create']}>
                                <div>Admin Page</div>
                            </PermissionRoute>
                        }
                    />
                </Route>
            </Routes>
        </MemoryRouter>,
    );
}

describe('PermissionRoute', () => {
    beforeEach(() => {
        localStorage.clear();
    });

    it('renders loading gate while auth context is unresolved', () => {
        renderWithContext(null, false, '/admin');
        expect(screen.getByTestId('permission-route-loading')).toBeInTheDocument();
    });

    it('allows route when required permission exists and auth resolved', () => {
        renderWithContext(
            {
                id: '1',
                discord_id: '1001',
                username: 'manager',
                nickname: 'Manager',
                role: 'manager',
                require_password_change: false,
                permissions: { 'events.create': true },
            },
            true,
            '/admin',
        );

        expect(screen.getByText('Admin Page')).toBeInTheDocument();
    });

    it('redirects to /hub when required permission is missing and auth resolved', () => {
        renderWithContext(
            {
                id: '1',
                discord_id: '1001',
                username: 'employee',
                nickname: 'Employee',
                role: 'employee',
                require_password_change: false,
                permissions: { 'events.create': false },
            },
            true,
            '/admin',
        );

        expect(screen.getByText('Hub Page')).toBeInTheDocument();
    });

    it('ignores stale localStorage user when context user is null', () => {
        localStorage.setItem(
            'user',
            JSON.stringify({
                id: 'stale',
                discord_id: '9999',
                username: 'stale',
                nickname: 'Stale',
                role: 'developer',
                require_password_change: false,
                permissions: { 'events.create': true },
            })
        );

        renderWithContext(null, true, '/admin');
        expect(screen.getByText('Hub Page')).toBeInTheDocument();
    });
});
