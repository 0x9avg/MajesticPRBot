import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
    apiFetch,
    clearSiteMaintenanceState,
    getSiteMaintenanceMessage,
    onLogout,
    onSiteMaintenance,
    readSiteMaintenanceMessage,
    setAccessToken,
    SITE_MAINTENANCE_EVENT,
} from '../client';

describe('api client maintenance handling', () => {
    beforeEach(() => {
        localStorage.clear();
        setAccessToken(null);
        clearSiteMaintenanceState();
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
        localStorage.clear();
        setAccessToken(null);
        clearSiteMaintenanceState();
    });

    it('reads maintenance messages from structured 503 responses', async () => {
        const response = new Response(JSON.stringify({
            detail: {
                code: 'SITE_MAINTENANCE',
                message: 'На сайте идут технические работы',
            },
        }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
        });

        await expect(readSiteMaintenanceMessage(response)).resolves.toBe('На сайте идут технические работы');
    });

    it('dispatches a maintenance event for direct SITE_MAINTENANCE responses without logging out', async () => {
        const logoutMock = vi.fn();
        onLogout(logoutMock);

        const maintenanceEvents: Array<{ message: string; source: string }> = [];
        const unsubscribe = onSiteMaintenance((detail) => {
            maintenanceEvents.push({ message: detail.message, source: detail.source });
        });

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({
                detail: {
                    code: 'SITE_MAINTENANCE',
                    message: 'Проводятся технические работы',
                },
            }), {
                status: 503,
                headers: { 'Content-Type': 'application/json' },
            })
        );
        vi.stubGlobal('fetch', fetchMock);

        try {
            const response = await apiFetch('/api/hub');

            expect(response.status).toBe(503);
            expect(maintenanceEvents).toEqual([
                { message: 'Проводятся технические работы', source: 'fetch' },
            ]);
            expect(getSiteMaintenanceMessage()).toBe('Проводятся технические работы');
            expect(logoutMock).not.toHaveBeenCalled();
        } finally {
            unsubscribe();
        }
    });

    it('dispatches a maintenance event when refresh returns SITE_MAINTENANCE', async () => {
        const logoutMock = vi.fn();
        onLogout(logoutMock);

        const maintenanceEvents: Array<{ message: string; source: string }> = [];
        const unsubscribe = onSiteMaintenance((detail) => {
            maintenanceEvents.push({ message: detail.message, source: detail.source });
        });

        const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
            const url = String(input);

            if (url.endsWith('/api/protected')) {
                return new Response(JSON.stringify({
                    detail: {
                        code: 'TOKEN_EXPIRED',
                        message: 'Токен доступа истёк',
                    },
                }), {
                    status: 401,
                    headers: { 'Content-Type': 'application/json' },
                });
            }

            if (url.endsWith('/api/auth/refresh')) {
                return new Response(JSON.stringify({
                    detail: {
                        code: 'SITE_MAINTENANCE',
                        message: 'Сайт временно недоступен',
                    },
                }), {
                    status: 503,
                    headers: { 'Content-Type': 'application/json' },
                });
            }

            return new Response('{}', { status: 404, headers: { 'Content-Type': 'application/json' } });
        });
        vi.stubGlobal('fetch', fetchMock);

        try {
            const response = await apiFetch('/api/protected');

            expect(response.status).toBe(503);
            expect(maintenanceEvents).toEqual([
                { message: 'Сайт временно недоступен', source: 'refresh' },
            ]);
            expect(getSiteMaintenanceMessage()).toBe('Сайт временно недоступен');
            expect(logoutMock).not.toHaveBeenCalled();
        } finally {
            unsubscribe();
        }
    });

    it('does not emit a maintenance event for non-maintenance 503 responses', async () => {
        const events: unknown[] = [];
        const unsubscribe = onSiteMaintenance((detail) => {
            events.push(detail);
        });

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ detail: 'service unavailable' }), {
                status: 503,
                headers: { 'Content-Type': 'application/json' },
            })
        );
        vi.stubGlobal('fetch', fetchMock);

        try {
            const response = await apiFetch('/api/hub');

            expect(response.status).toBe(503);
            expect(events).toEqual([]);
            expect(response.headers.get('content-type')).toContain('application/json');
        } finally {
            unsubscribe();
        }
    });

    it('exposes a shared event name for centralized listeners', () => {
        expect(SITE_MAINTENANCE_EVENT).toBe('pr:site-maintenance');
    });
});
