import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen, waitFor } from '@testing-library/react';
import ProtectedRoute from '../ProtectedRoute';

const authState = vi.hoisted(() => ({
    token: null as string | null,
    maintenanceMessage: null as string | null,
}));

// Mock the client module
vi.mock('../../api/client', () => ({
    getAccessToken: vi.fn(() => authState.token),
    getSiteMaintenanceMessage: vi.fn(() => authState.maintenanceMessage),
    tryRefresh: vi.fn(() => Promise.resolve(false)),
}));

import { getAccessToken, getSiteMaintenanceMessage, tryRefresh } from '../../api/client';

const mockedTryRefresh = vi.mocked(tryRefresh);
const mockedGetAccessToken = vi.mocked(getAccessToken);
const mockedGetSiteMaintenanceMessage = vi.mocked(getSiteMaintenanceMessage);

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
                <Route path="/maintenance" element={<div>Maintenance Page</div>} />
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
        authState.token = null;
        authState.maintenanceMessage = null;
        mockedTryRefresh.mockReset().mockResolvedValue(false);
        mockedGetAccessToken.mockImplementation(() => authState.token);
        mockedGetSiteMaintenanceMessage.mockImplementation(() => authState.maintenanceMessage);
    });

    it('redirects to login when token is missing and refresh fails', async () => {
        renderWithRoutes('/admin');
        await waitFor(() => {
            expect(screen.getByText('Login Page')).toBeInTheDocument();
        });
    });

    it('allows access when token exists and is not expired', async () => {
        const token = fakeJwt({ role: 'manager', exp: Date.now() / 1000 + 3600 });
        authState.token = token;

        renderWithRoutes('/admin', ['manager', 'developer']);
        await waitFor(() => {
            expect(screen.getByText('Admin Page')).toBeInTheDocument();
        });
    });

    it('redirects to hub when role is not allowed', async () => {
        const token = fakeJwt({ role: 'employee', exp: Date.now() / 1000 + 3600 });
        authState.token = token;

        renderWithRoutes('/admin', ['manager', 'developer']);
        await waitFor(() => {
            expect(screen.getByText('Hub Page')).toBeInTheDocument();
        });
    });

    it('redirects to login when role check is required but token has no role', async () => {
        const token = fakeJwt({ exp: Date.now() / 1000 + 3600 });
        authState.token = token;

        renderWithRoutes('/admin', ['manager']);
        await waitFor(() => {
            expect(screen.getByText('Login Page')).toBeInTheDocument();
        });
    });

    it('attempts refresh when token is expired and succeeds', async () => {
        // Set an expired token
        const expiredToken = fakeJwt({ role: 'manager', exp: Date.now() / 1000 - 60 });
        authState.token = expiredToken;

        // Mock successful refresh — tryRefresh updates the in-memory token
        const freshToken = fakeJwt({ role: 'manager', exp: Date.now() / 1000 + 3600 });
        mockedTryRefresh.mockImplementation(async () => {
            authState.token = freshToken;
            return true;
        });

        renderWithRoutes('/admin', ['manager']);
        await waitFor(() => {
            expect(screen.getByText('Admin Page')).toBeInTheDocument();
        });
        expect(mockedTryRefresh).toHaveBeenCalledOnce();
    });

    it('redirects to login when token is expired and refresh fails', async () => {
        const expiredToken = fakeJwt({ role: 'manager', exp: Date.now() / 1000 - 60 });
        authState.token = expiredToken;
        mockedTryRefresh.mockResolvedValue(false);

        renderWithRoutes('/admin');
        await waitFor(() => {
            expect(screen.getByText('Login Page')).toBeInTheDocument();
        });
        expect(mockedTryRefresh).toHaveBeenCalledOnce();
    });

    it('redirects to maintenance when refresh fails because site maintenance is active', async () => {
        authState.maintenanceMessage = 'Идут технические работы';
        mockedTryRefresh.mockResolvedValue(false);

        renderWithRoutes('/admin');
        await waitFor(() => {
            expect(screen.getByText('Maintenance Page')).toBeInTheDocument();
        });
    });

    it('attempts refresh when no token exists but cookie might be present', async () => {
        mockedTryRefresh.mockImplementation(async () => {
            const freshToken = fakeJwt({ role: 'employee', exp: Date.now() / 1000 + 3600 });
            authState.token = freshToken;
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
