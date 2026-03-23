import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({
    navigateMock: vi.fn(),
    apiFetchMock: vi.fn(),
    clearSiteMaintenanceStateMock: vi.fn(),
    getAccessTokenMock: vi.fn(),
    getSiteMaintenanceMessageMock: vi.fn(),
    readSiteMaintenanceMessageMock: vi.fn(),
    setAccessTokenMock: vi.fn(),
    tryRefreshMock: vi.fn(),
    locationState: { current: null as unknown },
}));

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
    return {
        ...actual,
        useNavigate: () => mocks.navigateMock,
        useLocation: () => ({ state: mocks.locationState.current }),
    };
});

vi.mock('../../api/client', () => ({
    apiFetch: mocks.apiFetchMock,
    clearSiteMaintenanceState: mocks.clearSiteMaintenanceStateMock,
    getAccessToken: mocks.getAccessTokenMock,
    getSiteMaintenanceMessage: mocks.getSiteMaintenanceMessageMock,
    readSiteMaintenanceMessage: mocks.readSiteMaintenanceMessageMock,
    setAccessToken: mocks.setAccessTokenMock,
    tryRefresh: mocks.tryRefreshMock,
}));

import MaintenancePage from '../MaintenancePage';

describe('MaintenancePage', () => {
    beforeEach(() => {
        localStorage.clear();
        mocks.navigateMock.mockReset();
        mocks.apiFetchMock.mockReset();
        mocks.clearSiteMaintenanceStateMock.mockReset();
        mocks.getAccessTokenMock.mockReset();
        mocks.getSiteMaintenanceMessageMock.mockReset();
        mocks.readSiteMaintenanceMessageMock.mockReset();
        mocks.setAccessTokenMock.mockReset();
        mocks.tryRefreshMock.mockReset();
        mocks.locationState.current = null;
        mocks.getAccessTokenMock.mockReturnValue('active-token');
        mocks.getSiteMaintenanceMessageMock.mockReturnValue(null);
        mocks.tryRefreshMock.mockResolvedValue(false);
    });

    it('renders fallback message when no runtime message is provided', () => {
        render(<MaintenancePage />);

        expect(screen.getByText('Технические работы')).toBeInTheDocument();
        expect(screen.getByText('На сайте ведутся технические работы. Попробуйте позже.')).toBeInTheDocument();
    });

    it('renders runtime message from location state', () => {
        mocks.locationState.current = { message: 'Сайт временно недоступен' };

        render(<MaintenancePage />);

        expect(screen.getByText('Сайт временно недоступен')).toBeInTheDocument();
    });

    it('keeps the user on maintenance and updates the message when backend still reports maintenance', async () => {
        mocks.locationState.current = { message: 'Начальное сообщение' };
        mocks.apiFetchMock.mockResolvedValue(
            new Response(JSON.stringify({
                detail: {
                    code: 'SITE_MAINTENANCE',
                    message: 'Технические работы продлены',
                },
            }), {
                status: 503,
                headers: { 'Content-Type': 'application/json' },
            })
        );
        mocks.readSiteMaintenanceMessageMock.mockResolvedValue('Технические работы продлены');

        const ui = userEvent.setup();
        render(<MaintenancePage />);

        await ui.click(screen.getByRole('button', { name: 'Обновить' }));

        await waitFor(() => {
            expect(mocks.apiFetchMock).toHaveBeenCalledWith('/api/auth/me');
            expect(screen.getByText('Технические работы продлены')).toBeInTheDocument();
        });

        expect(mocks.navigateMock).not.toHaveBeenCalled();
    });

    it('navigates to hub when backend reports the session is valid again', async () => {
        mocks.apiFetchMock.mockResolvedValue(
            new Response('{}', {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            })
        );
        mocks.readSiteMaintenanceMessageMock.mockResolvedValue(null);

        const ui = userEvent.setup();
        render(<MaintenancePage />);

        await ui.click(screen.getByRole('button', { name: 'Обновить' }));

        await waitFor(() => {
            expect(mocks.clearSiteMaintenanceStateMock).toHaveBeenCalled();
            expect(mocks.navigateMock).toHaveBeenCalledWith('/hub', { replace: true });
        });
    });

    it('navigates to login when there is no access token and refresh cannot restore the session', async () => {
        mocks.getAccessTokenMock.mockReturnValue(null);
        mocks.tryRefreshMock.mockResolvedValue(false);
        mocks.getSiteMaintenanceMessageMock.mockReturnValue(null);

        const ui = userEvent.setup();
        render(<MaintenancePage />);

        await ui.click(screen.getByRole('button', { name: 'Обновить' }));

        await waitFor(() => {
            expect(mocks.tryRefreshMock).toHaveBeenCalled();
            expect(mocks.setAccessTokenMock).toHaveBeenCalledWith(null);
            expect(mocks.navigateMock).toHaveBeenCalledWith('/login', { replace: true });
        });
    });

    it('logs out locally and navigates to login', async () => {
        localStorage.setItem('refresh_token', 'refresh-token');
        localStorage.setItem('user', '{"username":"tester"}');
        mocks.apiFetchMock.mockResolvedValue(
            new Response('{}', {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            })
        );

        const ui = userEvent.setup();
        render(<MaintenancePage />);

        await ui.click(screen.getByRole('button', { name: 'Выйти' }));

        await waitFor(() => {
            expect(mocks.apiFetchMock).toHaveBeenCalledWith('/api/auth/logout/current', { method: 'POST' });
            expect(mocks.setAccessTokenMock).toHaveBeenCalledWith(null);
            expect(mocks.clearSiteMaintenanceStateMock).toHaveBeenCalled();
            expect(mocks.navigateMock).toHaveBeenCalledWith('/login', { replace: true });
        });

        expect(localStorage.getItem('refresh_token')).toBeNull();
        expect(localStorage.getItem('user')).toBeNull();
    });
});
