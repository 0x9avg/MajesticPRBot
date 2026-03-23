import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { setAccessToken } from '../../../../api/client';
import SiteManagement from '../SiteManagement';

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

const initialServers = [
    { id: 1, full_name: 'Majestic #1', short_name: '#1', command_name: 'RU1', sort_order: 1, is_active: true },
    { id: 2, full_name: 'Majestic #2', short_name: '#2', command_name: 'RU2', sort_order: 2, is_active: true },
    { id: 19, full_name: 'Majestic #19', short_name: '#19', command_name: 'RU19', sort_order: 19, is_active: false },
];

const createFetchMock = () =>
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = (init?.method ?? 'GET').toUpperCase();

        if (url === '/api/game-servers' && method === 'GET') {
            return ok(initialServers);
        }

        if (url === '/api/guild/game-servers' && method === 'PUT') {
            const body = JSON.parse(String(init?.body ?? '{}')) as {
                items?: Array<{ id?: number; full_name: string; short_name: string; command_name: string; sort_order: number; is_active: boolean }>;
            };
            let nextAssignedId = 20;
            const savedItems = (body.items ?? []).map((item) => ({
                ...item,
                id: item.id ?? nextAssignedId++,
            }));
            return ok(savedItems);
        }

        return new Response('{}', { status: 404 });
    });

describe('SiteManagement', () => {
    beforeEach(() => {
        vi.stubGlobal('localStorage', createLocalStorageMock());
        setAccessToken('test-token');
    });

    afterEach(() => {
        setAccessToken(null);
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('loads servers, keeps existing ids readonly, deactivates saved rows, restores inactive rows, and omits ids for new rows', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);
        const ui = userEvent.setup();

        render(<SiteManagement />);

        await waitFor(() => {
            expect(screen.getByText('Игровые сервера')).toBeInTheDocument();
        });

        expect(screen.getByDisplayValue('Majestic #1')).toBeInTheDocument();
        expect(screen.getByDisplayValue('Majestic #19')).toBeInTheDocument();
        expect(screen.getByTestId('game-server-id-server-1')).toHaveTextContent('1');
        expect(screen.getByTestId('game-server-status-server-19')).toHaveTextContent('Неактивен');

        await ui.click(screen.getAllByRole('button', { name: 'Удалить сервер' })[0]);
        expect(screen.getByTestId('game-server-status-server-1')).toHaveTextContent('Неактивен');

        await ui.click(screen.getAllByRole('button', { name: 'Восстановить сервер' })[0]);
        expect(screen.getByTestId('game-server-status-server-1')).toHaveTextContent('Активен');

        const restoreButtons = screen.getAllByRole('button', { name: 'Восстановить сервер' });
        await ui.click(restoreButtons.at(-1) as HTMLElement);
        expect(screen.getByTestId('game-server-status-server-19')).toHaveTextContent('Активен');

        await ui.click(screen.getByRole('button', { name: 'Добавить сервер' }));

        await waitFor(() => {
            expect(screen.getByTestId('game-server-row-draft-1')).toBeInTheDocument();
        });

        expect(screen.getByTestId('game-server-id-draft-1')).toHaveTextContent('Будет назначен');

        await ui.type(screen.getByTestId('game-server-full-draft-1'), 'Majestic #20');
        await ui.type(screen.getByTestId('game-server-short-draft-1'), '#20');
        await ui.type(screen.getByTestId('game-server-command-draft-1'), 'RU20');
        await ui.clear(screen.getByTestId('game-server-sort-draft-1'));
        await ui.type(screen.getByTestId('game-server-sort-draft-1'), '20');

        await ui.click(screen.getByRole('button', { name: 'Сохранить каталог' }));

        await waitFor(() => {
            const putCall = fetchMock.mock.calls.find(([requestUrl, requestInit]) => (
                String(requestUrl) === '/api/guild/game-servers'
                && (requestInit as RequestInit | undefined)?.method === 'PUT'
            ));
            expect(putCall).toBeTruthy();
        });

        const putCall = fetchMock.mock.calls.find(([requestUrl, requestInit]) => (
            String(requestUrl) === '/api/guild/game-servers'
            && (requestInit as RequestInit | undefined)?.method === 'PUT'
        ));
        const body = JSON.parse(String((putCall?.[1] as RequestInit | undefined)?.body ?? '{}')) as {
            items: Array<{ id?: number; full_name: string; short_name: string; command_name: string; sort_order: number; is_active: boolean }>;
        };

        const newRowPayload = body.items.find((item) => item.full_name === 'Majestic #20');
        expect(newRowPayload).toMatchObject({
            full_name: 'Majestic #20',
            short_name: '#20',
            command_name: 'RU20',
            sort_order: 20,
            is_active: true,
        });
        expect(newRowPayload).not.toHaveProperty('id');
        expect(body.items.find((item) => item.id === 19)?.is_active).toBe(true);

        await waitFor(() => {
            expect(screen.getByDisplayValue('Majestic #20')).toBeInTheDocument();
            expect(screen.getByTestId('game-server-id-server-20')).toHaveTextContent('20');
        });
    });
});
