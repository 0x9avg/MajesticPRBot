import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SanctionsQueueManagement from '../SanctionsQueueManagement';
import { setAccessToken } from '../../../../api/client';
import { formatMskToLocal } from '../../../../utils/datetime';

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
    gross_points: 12.5,
    net_points: 9.5,
    active_point_penalty: 0,
    active_percent_penalty: 0,
    active_warnings_display: '0/2 0/2',
};

const settings = {
    check_cycle_size: 5,
    check_immunity_hours_per_day: 4,
    point_immunity_hours_per_day: 5,
    percent_immunity_hours_per_day: 6,
    check_relief_hours_per_day: 4,
    point_relief_hours_per_day: 5,
    percent_relief_hours_per_day: 6,
    check_relief_min_streak_days: 2,
    point_relief_min_streak_days: 2,
    percent_relief_min_streak_days: 2,
    percent_relief_step_amount: 3,
    daily_norm_spec: 4,
    daily_norm_complaints: 0,
    daily_norm_mchat: 0,
};

const defaultRules = [
    { range_start: 1, range_end: 2, penalty_kind: 'point', penalty_amount: 1 },
    { range_start: 3, range_end: 3, penalty_kind: 'point', penalty_amount: 2 },
    { range_start: 4, range_end: 5, penalty_kind: 'percent', penalty_amount: 3 },
    { range_start: 6, range_end: 6, penalty_kind: 'percent', penalty_amount: 5 },
    { range_start: 7, range_end: 7, penalty_kind: 'oral', penalty_amount: 1 },
    { range_start: 8, range_end: null, penalty_kind: 'strict', penalty_amount: 1 },
];

const ok = (payload: unknown) =>
    new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
    });

const createFetchMock = (rulesPayload = defaultRules) =>
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);

        if (url.endsWith('/api/assistants')) {
            return ok({ status: 'success', data: [assistant] });
        }
        if (url.endsWith('/api/sanction-operations')) {
            return ok({
                status: 'success',
                data: [
                    {
                        id: '1',
                        operation_date: '2026-03-17',
                        created_at: '2026-03-15T08:30:00',
                        queued_at: '2026-03-17T09:45:00',
                        penalty_kind: 'check',
                        penalty_amount: 1,
                        recipient_mode: 'selected_only',
                        status: 'queued',
                        effective_members: 2,
                        issued_members: 0,
                        workoff_items: [],
                        members: [],
                    },
                    {
                        id: '2',
                        operation_date: '2026-03-14',
                        created_at: '2026-03-14T00:00:00',
                        queued_at: '2026-03-14T11:15:00',
                        penalty_kind: 'oral',
                        penalty_amount: 1,
                        recipient_mode: 'all_active',
                        status: 'completed',
                        processing_mode: 'nightly_auto',
                        processed_by_name: 'Система',
                        effective_members: 3,
                        issued_members: 3,
                        workoff_items: [],
                        members: [],
                    },
                ],
            });
        }
        if (url.endsWith('/api/sanction-settings')) {
            return ok({ status: 'success', data: settings });
        }
        if (url.endsWith('/api/sanction-settings/check-rules')) {
            return ok({ status: 'success', data: rulesPayload });
        }
        if (url.startsWith('/api/sanction-operations/')) {
            return ok({ status: 'success', data: {} });
        }
        return new Response('{}', { status: 404 });
    });

describe('SanctionsQueueManagement', () => {
    beforeEach(() => {
        vi.stubGlobal('localStorage', createLocalStorageMock());
        setAccessToken('test-token');
    });

    afterEach(() => {
        setAccessToken(null);
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('uses current-only settings endpoints and renders queued_at in history', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        render(<SanctionsQueueManagement />);

        await waitFor(() => {
            expect(screen.getByText('Очередь выдачи')).toBeInTheDocument();
        });

        expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/sanction-settings')).toBe(true);
        expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/sanction-settings/check-rules')).toBe(true);

        const user = userEvent.setup();
        await user.click(screen.getByRole('button', { name: 'История выдач' }));

        await waitFor(() => {
            expect(screen.getByText(formatMskToLocal('2026-03-14T11:15:00'))).toBeInTheDocument();
        });

        expect(screen.queryByText(formatMskToLocal('2026-03-14T00:00:00'))).not.toBeInTheDocument();
    });

    it('hides amount for check and requires auto relief date for warnings', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        const user = userEvent.setup();
        render(<SanctionsQueueManagement />);

        await waitFor(() => {
            expect(screen.getByText('Выдать общую санкцию')).toBeInTheDocument();
        });

        expect(screen.queryByText('Размер наказания')).not.toBeInTheDocument();

        await user.click(screen.getAllByText('Галка')[0]);
        await user.click(screen.getByText('Устный'));

        await waitFor(() => {
            expect(screen.getByText('Дата автоснятия')).toBeInTheDocument();
            expect(screen.queryByText('Размер наказания')).not.toBeInTheDocument();
        });

        await user.click(screen.getByRole('button', { name: 'Создать операцию' }));

        await waitFor(() => {
            expect(screen.getByText('Для устного и строгого наказания укажи дату автоснятия')).toBeInTheDocument();
        });

        const createCalls = fetchMock.mock.calls.filter(([url, init]) => (
            String(url) === '/api/sanction-operations' && (init as RequestInit | undefined)?.method === 'POST'
        ));
        expect(createCalls).toHaveLength(0);
    });

    it('rejects saving an empty check rule set on the frontend', async () => {
        const fetchMock = createFetchMock([]);
        vi.stubGlobal('fetch', fetchMock);

        const user = userEvent.setup();
        render(<SanctionsQueueManagement />);

        await waitFor(() => {
            expect(screen.getByText('Настройки санкций')).toBeInTheDocument();
        });

        await user.click(screen.getByRole('button', { name: 'Настройки санкций' }));
        await user.click(screen.getByRole('button', { name: 'Сохранить настройки' }));

        await waitFor(() => {
            expect(screen.getByText('Нельзя сохранить пустой набор правил галок')).toBeInTheDocument();
        });

        const putRulesCalls = fetchMock.mock.calls.filter(([url, init]) => (
            String(url) === '/api/sanction-settings/check-rules' && (init as RequestInit | undefined)?.method === 'PUT'
        ));
        expect(putRulesCalls).toHaveLength(0);
    });
});
