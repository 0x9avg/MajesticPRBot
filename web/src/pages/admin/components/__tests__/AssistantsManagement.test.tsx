import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AssistantsManagement from '../AssistantsManagement';

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

const assistant = {
    pr_id: 101,
    nickname: 'Tester',
    role: 'employee',
    experience_days: 5,
    status: 'free',
    assigned_to_type: null,
    assigned_to_name: null,
    total_spec_seconds: 0,
    total_spec_hours: 0,
    display_points: 0,
    penalty_points: 0,
    penalty_percent: 0,
    warnings_display: '0/2 0/2',
};

const ok = (payload: unknown) =>
    new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
    });

const createFetchMock = () =>
    vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);

        if (url.includes('/api/assistants/101/sessions')) {
            return ok({ status: 'success', data: [] });
        }
        if (url.endsWith('/api/assistants/101')) {
            return ok({ status: 'success', data: assistant });
        }
        if (url.endsWith('/api/assistants')) {
            return ok({ status: 'success', data: [assistant] });
        }
        if (url.endsWith('/api/streamers')) {
            return ok({
                status: 'success',
                data: {
                    streamers: [
                        { streamer_id: 1, streamer_name: 'alpha', is_online: true },
                        { streamer_id: 2, streamer_name: 'beta', is_online: false },
                    ],
                },
            });
        }
        if (url.endsWith('/api/events')) {
            return ok({
                status: 'success',
                data: [
                    { id: 10, name: 'Event A', is_active: true },
                    { id: 11, name: 'Event B', is_active: false },
                ],
            });
        }
        return new Response('{}', { status: 404 });
    });

describe('AssistantsManagement', () => {
    beforeEach(() => {
        vi.stubGlobal('localStorage', createLocalStorageMock());
        localStorage.setItem('access_token', 'test-token');
    });

    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('shows selectors for streamers and events in add form', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        const user = userEvent.setup();
        render(<AssistantsManagement />);

        await waitFor(() => {
            expect(screen.getByText('Выберите стримера')).toBeInTheDocument();
        });

        const typeSelect = screen.getAllByRole('combobox')[0];
        await user.selectOptions(typeSelect, 'event');

        await waitFor(() => {
            expect(screen.getByText('Выберите событие')).toBeInTheDocument();
        });
    });

    it('keeps manual mode and requires comment', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        const user = userEvent.setup();
        render(<AssistantsManagement />);

        await waitFor(() => {
            expect(screen.getByText('Выберите стримера')).toBeInTheDocument();
        });

        const typeSelect = screen.getAllByRole('combobox')[0];
        await user.selectOptions(typeSelect, 'manual');

        await user.click(screen.getByRole('button', { name: 'Добавить ручную сессию' }));

        await waitFor(() => {
            expect(screen.getByText('Для manual-сессии обязателен комментарий')).toBeInTheDocument();
        });
    });
});

