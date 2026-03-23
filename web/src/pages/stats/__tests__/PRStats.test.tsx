import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import PRStats from '../PRStats';
import { setAccessToken } from '../../../api/client';
import type { UserContext } from '../../../types/auth';

let mockedUser: UserContext | null = null;

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
    return {
        ...actual,
        useOutletContext: () => ({ user: mockedUser }),
    };
});

const createLocalStorageMock = () => {
    const storage: Record<string, string> = {};
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

const assistantsPayload = {
    status: 'success',
    data: [
        {
            pr_id: '1001',
            nickname: 'Tester',
            role: 'employee',
            experience_days: 12,
            status: 'free',
            total_spec_hours: 48,
            avg_spec_hours_per_day_30d: 4,
            gross_points: 120,
            net_points: 110,
            active_point_penalty: 10,
            active_percent_penalty: 0,
            active_strict_warnings: 0,
            active_oral_warnings: 1,
        },
    ],
};

const makeWeeklyDays = () => ([
    {
        work_date: '2026-03-16',
        spec_hours_on_day: 4,
        mchat_count: 1,
        complaints_count: 0,
        resolved_status: null,
    },
    {
        work_date: '2026-03-17',
        spec_hours_on_day: 5,
        mchat_count: 0,
        complaints_count: 1,
        resolved_status: 'O',
    },
    {
        work_date: '2026-03-18',
        spec_hours_on_day: 3,
        mchat_count: 0,
        complaints_count: 0,
        resolved_status: null,
    },
    {
        work_date: '2026-03-19',
        spec_hours_on_day: 4,
        mchat_count: 0,
        complaints_count: 0,
        resolved_status: null,
    },
    {
        work_date: '2026-03-20',
        spec_hours_on_day: 4,
        mchat_count: 0,
        complaints_count: 0,
        resolved_status: null,
    },
    {
        work_date: '2026-03-21',
        spec_hours_on_day: 2,
        mchat_count: 0,
        complaints_count: 0,
        resolved_status: null,
    },
    {
        work_date: '2026-03-22',
        spec_hours_on_day: 1,
        mchat_count: 0,
        complaints_count: 0,
        resolved_status: null,
    },
]);

const weeklyPayload = {
    status: 'success',
    data: {
        week_start: '2026-03-16',
        week_end: '2026-03-22',
        day_labels: [
            { work_date: '2026-03-16', label: 'Пн' },
            { work_date: '2026-03-17', label: 'Вт' },
            { work_date: '2026-03-18', label: 'Ср' },
            { work_date: '2026-03-19', label: 'Чт' },
            { work_date: '2026-03-20', label: 'Пт' },
            { work_date: '2026-03-21', label: 'Сб' },
            { work_date: '2026-03-22', label: 'Вс' },
        ],
        items: [
            {
                assistant_id: '1001',
                nickname: 'Tester',
                role: 'employee',
                week_start: '2026-03-16',
                week_end: '2026-03-22',
                days: makeWeeklyDays(),
                total_spec_hours: 23,
                total_mchat: 1,
                total_complaints: 1,
                suggested_result: 'Инактив',
                selected_result: null,
                result_display: 'Инактив',
                count_P: 0,
                count_U: 0,
                count_O: 0,
                payout_type: null,
                payout_server_id: null,
                payout_static: null,
                generated_payout_command: null,
                generated_payout_available: false,
                generated_payout_reason: null,
            },
        ],
    },
};

const createFetchMock = () =>
    vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/assistants') {
            return new Response(JSON.stringify(assistantsPayload), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }
        if (url === '/api/assistant-weekly/current') {
            return new Response(JSON.stringify(weeklyPayload), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }
        return new Response('{}', { status: 404 });
    });

describe('PRStats weekly tab', () => {
    beforeEach(() => {
        vi.stubGlobal('localStorage', createLocalStorageMock());
        setAccessToken(null);
        mockedUser = {
            id: '1',
            discord_id: '1001',
            username: 'tester',
            nickname: 'Tester',
            role: 'employee',
            require_password_change: false,
            permissions: {
                'assistants.view': true,
            },
        };
    });

    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('keeps the legacy table and renders the weekly active spreadsheet tab', async () => {
        vi.stubGlobal('fetch', createFetchMock());
        const ui = userEvent.setup();

        render(
            <MemoryRouter initialEntries={['/assistants']}>
                <PRStats />
            </MemoryRouter>
        );

        await waitFor(() => {
            expect(screen.getByText('Таблица PR Ассистентов')).toBeInTheDocument();
        });

        expect(screen.getByText('Tester')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Актив' })).toBeInTheDocument();

        await ui.click(screen.getByRole('link', { name: 'Актив' }));

        await waitFor(() => {
            expect(screen.getByText('16.03')).toBeInTheDocument();
            expect(screen.getByText('Tester')).toBeInTheDocument();
            expect(screen.getByText('Ассистент', { selector: 'span' })).toBeInTheDocument();
            expect(screen.getByText('Итоги')).toBeInTheDocument();
            expect(screen.getByText('23ч')).toBeInTheDocument();
        });

        expect(screen.queryByText('Инактив')).not.toBeInTheDocument();
        expect(screen.queryByText('1001')).not.toBeInTheDocument();
        expect(screen.queryByText('—', { selector: 'span' })).not.toBeInTheDocument();
    });
});
