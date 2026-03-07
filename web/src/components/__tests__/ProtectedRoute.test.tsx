import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen, waitFor } from '@testing-library/react';
import ProtectedRoute from '../ProtectedRoute';

// Mock the client module
vi.mock('../../api/client', () => ({
    hydrateAccessTokenFromStorage: vi.fn(() => null),
    tryRefresh: vi.fn(() => Promise.resolve(false)),
}));

import { hydrateAccessTokenFromStorage, tryRefresh } from '../../api/client';

const mockedTryRefresh = vi.mocked(tryRefresh);
const mockedHydrate = vi.mocked(hydrateAccessTokenFromStorage);

/**
 * Helper: build a fake JWT with the given payload (no real signature).
 * Only the payload (part[1]) is read by ProtectedRoute.
 */
function fakeJwt(payload: Record<string, unknown>): string {
    const header = btoa(JSON.stringify({ alg: 'none' }));
    const body = btoa(JSON.stringify(payload));
    return `${header}.${body}.fakesig`;
}

const renderWithRoutes = (initialPath: string, allowedRoles?: string[]) => {
    render(
        <MemoryRouter initialEntries={[initialPath]}>
            <Routes>
                <Route path="/login" element={<div>Login Page</div>} />
                <Route path="/hub" element={<div>Hub Page</div>} />
                <Route element={<ProtectedRoute allowedRoles={allowedRoles} />}>
                    <Route path="/admin" element={<div>Admin Page</div>} />
                </Route>
            </Routes>
        </MemoryRouter>
    );
};

describe('ProtectedRoute', () => {
    beforeEach(() => {
        localStorage.clear();
        mockedTryRefresh.mockReset().mockResolvedValue(false);
        mockedHydrate.mockReset().mockReturnValue(null);
    });

    it('redirects to login when token is missing and refresh fails', async () => {
        renderWithRoutes('/admin');
        await waitFor(() => {
            expect(screen.getByText('Login Page')).toBeInTheDocument();
        });
    });

    it('allows access when token exists and is not expired', async () => {
        const token = fakeJwt({ role: 'manager', exp: Date.now() / 1000 + 3600 });
        localStorage.setItem('access_token', token);
        localStorage.setItem('user', JSON.stringify({ role: 'manager' }));

        renderWithRoutes('/admin', ['manager', 'developer']);
        await waitFor(() => {
            expect(screen.getByText('Admin Page')).toBeInTheDocument();
        });
    });

    it('redirects to hub when role is not allowed', async () => {
        const token = fakeJwt({ role: 'employee', exp: Date.now() / 1000 + 3600 });
        localStorage.setItem('access_token', token);
        localStorage.setItem('user', JSON.stringify({ role: 'employee' }));

        renderWithRoutes('/admin', ['manager', 'developer']);
        await waitFor(() => {
            expect(screen.getByText('Hub Page')).toBeInTheDocument();
        });
    });

    it('redirects to login when role check is required but user payload is broken', async () => {
        const token = fakeJwt({ exp: Date.now() / 1000 + 3600 });
        localStorage.setItem('access_token', token);
        localStorage.setItem('user', '{broken-json');

        renderWithRoutes('/admin', ['manager']);
        await waitFor(() => {
            expect(screen.getByText('Login Page')).toBeInTheDocument();
        });
    });

    it('attempts refresh when token is expired and succeeds', async () => {
        // Set an expired token
        const expiredToken = fakeJwt({ role: 'manager', exp: Date.now() / 1000 - 60 });
        localStorage.setItem('access_token', expiredToken);

        // Mock successful refresh — tryRefresh updates the in-memory token
        const freshToken = fakeJwt({ role: 'manager', exp: Date.now() / 1000 + 3600 });
        mockedTryRefresh.mockImplementation(async () => {
            localStorage.setItem('access_token', freshToken);
            return true;
        });
        localStorage.setItem('user', JSON.stringify({ role: 'manager' }));

        renderWithRoutes('/admin', ['manager']);
        await waitFor(() => {
            expect(screen.getByText('Admin Page')).toBeInTheDocument();
        });
        expect(mockedTryRefresh).toHaveBeenCalledOnce();
    });

    it('redirects to login when token is expired and refresh fails', async () => {
        const expiredToken = fakeJwt({ role: 'manager', exp: Date.now() / 1000 - 60 });
        localStorage.setItem('access_token', expiredToken);
        mockedTryRefresh.mockResolvedValue(false);

        renderWithRoutes('/admin');
        await waitFor(() => {
            expect(screen.getByText('Login Page')).toBeInTheDocument();
        });
        expect(mockedTryRefresh).toHaveBeenCalledOnce();
    });

    it('attempts refresh when no token exists but cookie might be present', async () => {
        mockedTryRefresh.mockImplementation(async () => {
            const freshToken = fakeJwt({ role: 'employee', exp: Date.now() / 1000 + 3600 });
            localStorage.setItem('access_token', freshToken);
            return true;
        });

        renderWithRoutes('/admin');
        await waitFor(() => {
            // Should pass auth but redirect to hub since employee isn't in allowedRoles
            // Actually /admin has no allowedRoles in this call, so it allows access
        });
        expect(mockedTryRefresh).toHaveBeenCalledOnce();
    });
});
