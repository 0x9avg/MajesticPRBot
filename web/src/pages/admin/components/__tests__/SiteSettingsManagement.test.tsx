import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { UserContext } from '../../../../types/auth';

import { setAccessToken } from '../../../../api/client';
import RbacManagement from '../RbacManagement';
import SiteMaintenanceManagement from '../SiteMaintenanceManagement';

type StorageDict = Record<string, string>;

const createLocalStorageMock = () => {
    const storage: StorageDict = {};
    return {
        getItem: vi.fn((key: string) => (key in storage ? storage[key] : null)),
        setItem: vi.fn((key: string, value: string) => {
            storage[key] = String(value);
        }),
        removeItem: vi.fn((key: string) => {
            delete storage[key];
        }),
        clear: vi.fn(() => {
            Object.keys(storage).forEach((key) => delete storage[key]);
        }),
    };
};

const ok = (payload: unknown) =>
    new Response(JSON.stringify({ status: 'success', data: payload }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
    });

let mockedUser: UserContext | null = null;

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
    return {
        ...actual,
        useOutletContext: () => ({ user: mockedUser }),
    };
});

const rbacSnapshot = {
    roles: ['junior_employee', 'manager', 'developer'],
    permissions: [
        'dashboard.view',
        'rbac.view',
        'rbac.update',
        'site.maintenance.view',
        'site.maintenance.update',
        'assistants.view',
        'assistants.sessions.view',
        'assistants.sessions.manage',
    ],
    matrix: {
        junior_employee: {
            'dashboard.view': true,
            'rbac.view': false,
            'rbac.update': false,
            'site.maintenance.view': false,
            'site.maintenance.update': false,
            'assistants.view': false,
            'assistants.sessions.view': false,
            'assistants.sessions.manage': false,
        },
        manager: {
            'dashboard.view': true,
            'rbac.view': false,
            'rbac.update': false,
            'site.maintenance.view': false,
            'site.maintenance.update': false,
            'assistants.view': false,
            'assistants.sessions.view': false,
            'assistants.sessions.manage': false,
        },
        developer: {
            'dashboard.view': true,
            'rbac.view': true,
            'rbac.update': true,
            'site.maintenance.view': true,
            'site.maintenance.update': true,
            'assistants.view': true,
            'assistants.sessions.view': true,
            'assistants.sessions.manage': true,
        },
    },
    permission_implications: {
        'assistants.sessions.manage': ['assistants.sessions.view', 'assistants.view'],
        'rbac.update': ['rbac.view'],
        'site.maintenance.update': ['site.maintenance.view'],
    },
};

const createFetchMock = () =>
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = (init?.method ?? 'GET').toUpperCase();

        if (url === '/api/admin/rbac' && method === 'GET') {
            return ok(rbacSnapshot);
        }

        if (url === '/api/admin/rbac' && method === 'PUT') {
            const body = JSON.parse(String(init?.body ?? '{}')) as { matrix?: unknown };
            return ok({
                ...rbacSnapshot,
                matrix: body.matrix ?? rbacSnapshot.matrix,
            });
        }

        if (url === '/api/admin/site-maintenance' && method === 'GET') {
            return ok({ enabled: false });
        }

        if (url === '/api/admin/site-maintenance' && method === 'PATCH') {
            const body = JSON.parse(String(init?.body ?? '{}')) as { enabled?: boolean };
            return ok({ enabled: Boolean(body.enabled) });
        }

        return new Response('{}', { status: 404 });
    });

describe('RbacManagement', () => {
    beforeEach(() => {
        vi.stubGlobal('localStorage', createLocalStorageMock());
        setAccessToken('test-token');
        mockedUser = {
            id: '7',
            discord_id: '7001',
            username: 'developer',
            nickname: 'Developer',
            role: 'developer',
            require_password_change: false,
            permissions: {
                'rbac.view': true,
                'rbac.update': true,
                'site.maintenance.view': true,
                'site.maintenance.update': true,
            },
        };
    });

    afterEach(() => {
        setAccessToken(null);
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('loads matrix and saves through /api/admin/rbac', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);
        const ui = userEvent.setup();

        render(<RbacManagement />);

        await waitFor(() => {
            expect(screen.getByText('RBAC')).toBeInTheDocument();
        });

        expect(screen.getByTestId('rbac-cell-developer-rbac.update')).toBeChecked();
        expect(screen.getByTestId('rbac-cell-developer-site.maintenance.update')).toBeChecked();
        expect(screen.getByTestId('rbac-cell-developer-assistants.sessions.view')).toBeChecked();
        expect(screen.getByTestId('rbac-cell-developer-assistants.sessions.view')).toBeDisabled();

        await ui.click(screen.getByTestId('rbac-cell-manager-rbac.update'));
        await ui.click(screen.getByRole('button', { name: 'Сохранить матрицу' }));

        await waitFor(() => {
            const putCall = fetchMock.mock.calls.find(([requestUrl, requestInit]) => (
                String(requestUrl) === '/api/admin/rbac'
                && (requestInit as RequestInit | undefined)?.method === 'PUT'
            ));
            expect(putCall).toBeTruthy();
        });

        const putCall = fetchMock.mock.calls.find(([requestUrl, requestInit]) => (
            String(requestUrl) === '/api/admin/rbac'
            && (requestInit as RequestInit | undefined)?.method === 'PUT'
        ));
        const putBody = JSON.parse(String((putCall?.[1] as RequestInit | undefined)?.body ?? '{}')) as {
            matrix: Record<string, Record<string, boolean>>;
        };

        expect(putBody.matrix.manager['rbac.update']).toBe(true);
        expect(putBody.matrix.manager['rbac.view']).toBe(true);
    });
});

describe('SiteMaintenanceManagement', () => {
    beforeEach(() => {
        vi.stubGlobal('localStorage', createLocalStorageMock());
        setAccessToken('test-token');
        mockedUser = {
            id: '7',
            discord_id: '7001',
            username: 'developer',
            nickname: 'Developer',
            role: 'developer',
            require_password_change: false,
            permissions: {
                'site.maintenance.view': true,
                'site.maintenance.update': true,
            },
        };
    });

    afterEach(() => {
        setAccessToken(null);
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('loads and saves maintenance flag through dedicated endpoint', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);
        const ui = userEvent.setup();

        render(<SiteMaintenanceManagement />);

        await waitFor(() => {
            expect(screen.getByText('Тех. работы')).toBeInTheDocument();
        });

        const toggle = screen.getByTestId('site-maintenance-toggle') as HTMLInputElement;
        expect(toggle.checked).toBe(false);

        await ui.click(toggle);
        await ui.click(screen.getByRole('button', { name: 'Сохранить режим' }));

        await waitFor(() => {
            const patchCall = fetchMock.mock.calls.find(([requestUrl, requestInit]) => (
                String(requestUrl) === '/api/admin/site-maintenance'
                && (requestInit as RequestInit | undefined)?.method === 'PATCH'
            ));
            expect(patchCall).toBeTruthy();
        });

        const patchCall = fetchMock.mock.calls.find(([requestUrl, requestInit]) => (
            String(requestUrl) === '/api/admin/site-maintenance'
            && (requestInit as RequestInit | undefined)?.method === 'PATCH'
        ));
        const patchBody = JSON.parse(String((patchCall?.[1] as RequestInit | undefined)?.body ?? '{}')) as { enabled: boolean };
        expect(patchBody.enabled).toBe(true);
    });
});
