import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { setAccessToken } from '../../../../api/client';
import type { UserContext } from '../../../../types/auth';
import AssistantsManagement from '../AssistantsManagement';

type StorageDict = Record<string, string>;

interface FetchMockOptions {
    sessionsStatus?: number;
    sessionsPayload?: unknown;
}

type TestUserContext = UserContext & {
    manageable_roles?: Array<UserContext['role']>;
};

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
    active_strict_warnings: 0,
    active_oral_warnings: 0,
};

const higherAssistant = {
    ...assistant,
    pr_id: 202,
    nickname: 'Boss',
    role: 'developer',
};

const sessionRecord = {
    id: 77,
    pr_id: 101,
    target_type: 'streamer',
    target_id: 1,
    target_name: 'alpha',
    started_at: '2026-03-21T10:00:00',
    ended_at: '2026-03-21T11:00:00',
    duration_seconds: 3600,
    credited_points: 2.5,
    priority_auto: 2,
    priority_override: null,
    is_probation: false,
};

const dayStatus = {
    assistant_id: '101',
    work_date: '2026-03-16',
    spec_seconds_on_day: 0,
    spec_hours_on_day: 0,
    spec_points_auto: 0,
    manual_points_delta: 0,
    mchat_count: 0,
    complaints_count: 0,
    check_immunity: false,
    point_immunity: false,
    percent_immunity: false,
    streak_check_days: 0,
    streak_point_days: 0,
    streak_percent_days: 0,
};

const sanctions = [
    {
        sanction_id: 'sanction-1',
        assistant_id: '101',
        kind: 'oral',
        amount_total: 1,
        relieved_amount: 0,
        active_amount: 1,
        issued_at: '2026-03-10T09:00:00',
        display_issued_at: '2026-03-12T11:15:00',
        source_type: 'manual',
        auto_relief_date: '2026-03-20',
        workoff_items: [
            {
                metric: 'spec',
                multiplier: 1,
                period_start: '2026-03-20',
                period_end: '2026-03-22',
                required_work_days: 3,
                counted_work_days: 2,
                effective_period_end: '2026-03-24',
                uo_days_count: 1,
                status: 'pending',
                days: [
                    {
                        date: '2026-03-20',
                        manual_status: 'P',
                        counts_for_workoff: true,
                        required_amount: 4,
                        actual_amount: 4,
                        day_status: 'completed',
                    },
                    {
                        date: '2026-03-21',
                        manual_status: 'U',
                        counts_for_workoff: false,
                        required_amount: 4,
                        actual_amount: 0,
                        day_status: 'leave_skipped',
                    },
                ],
            },
        ],
        workoff_progress_summary: {
            has_workoff: true,
            total_items: 1,
            completed_items: 0,
            items: [
                {
                    metric: 'spec',
                    multiplier: 1,
                    period_start: '2026-03-20',
                    period_end: '2026-03-22',
                    required_work_days: 3,
                    counted_work_days: 2,
                    effective_period_end: '2026-03-24',
                    uo_days_count: 1,
                    status: 'pending',
                    days: [
                        {
                            date: '2026-03-20',
                            manual_status: 'P',
                            counts_for_workoff: true,
                            required_amount: 4,
                            actual_amount: 4,
                            day_status: 'completed',
                        },
                        {
                            date: '2026-03-21',
                            manual_status: 'U',
                            counts_for_workoff: false,
                            required_amount: 4,
                            actual_amount: 0,
                            day_status: 'leave_skipped',
                        },
                    ],
                },
            ],
        },
    },
];

const fullAccessUser: TestUserContext = {
    id: '1',
    discord_id: '1001',
    username: 'manager',
    nickname: 'Manager',
    role: 'manager',
    require_password_change: false,
    permissions: {
        'assistants.view': true,
        'assistants.sessions.view': true,
        'assistants.sessions.manage': true,
        'assistants.points.update': true,
        'assistants.sanctions.manage': true,
        'assistants.warnings.manage': true,
        'admin.users.role.update': true,
        'admin.users.deactivate': true,
    },
    manageable_roles: ['junior_employee', 'employee', 'senior_employee'],
};

const manageOnlyAssistantUser: TestUserContext = {
    ...fullAccessUser,
    permissions: {
        'assistants.view': true,
        'assistants.sessions.view': true,
        'assistants.sessions.manage': true,
        'assistants.points.update': true,
        'assistants.sanctions.manage': true,
        'assistants.warnings.manage': true,
        'admin.users.role.update': true,
        'admin.users.deactivate': true,
    },
    manageable_roles: ['junior_employee', 'employee', 'senior_employee'],
};

const readOnlySessionsUser: TestUserContext = {
    ...fullAccessUser,
    permissions: {
        'assistants.view': true,
        'assistants.sessions.view': true,
    },
    manageable_roles: ['junior_employee', 'employee', 'senior_employee'],
};

const ok = (payload: unknown) =>
    new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
    });

const createFetchMock = ({ sessionsStatus = 200, sessionsPayload = [sessionRecord] }: FetchMockOptions = {}) =>
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);

        if (url.endsWith('/api/sanctions/workoff-preview')) {
            const body = JSON.parse(String(init?.body || '{}')) as { assistant_ids?: Array<string | number> };
            expect(body.assistant_ids).toEqual(['101']);
            return ok({
                status: 'success',
                data: {
                    assistants: [
                        {
                            assistant_id: '101',
                            nickname: 'Tester',
                            items: [
                                {
                                    metric: 'spec',
                                    multiplier: 1,
                                    period_start: '2026-03-20',
                                    period_end: '2026-03-22',
                                    required_work_days: 3,
                                    counted_work_days: 2,
                                    effective_period_end: '2026-03-24',
                                    uo_days_count: 1,
                                    status: 'pending',
                                    days: [
                                        {
                                            date: '2026-03-20',
                                            manual_status: 'P',
                                            counts_for_workoff: true,
                                            required_amount: 4,
                                            actual_amount: 4,
                                            day_status: 'completed',
                                        },
                                        {
                                            date: '2026-03-21',
                                            manual_status: 'U',
                                            counts_for_workoff: false,
                                            required_amount: 4,
                                            actual_amount: 0,
                                            day_status: 'leave_skipped',
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            });
        }
        if (url.endsWith('/api/assistants/session-targets')) {
            return ok({
                status: 'success',
                data: {
                    streamers: [
                        { streamer_id: '1', streamer_name: 'alpha', is_online: true, priority: 2 },
                        { streamer_id: '2', streamer_name: 'beta', is_online: false, priority: 1 },
                    ],
                    events: [
                        { id: '10', name: 'Event A', is_active: true, priority: 3 },
                        { id: '11', name: 'Event B', is_active: false, priority: 1 },
                    ],
                },
            });
        }
        if (url.includes('/api/assistants/101/sessions')) {
            if (sessionsStatus !== 200) {
                return new Response(JSON.stringify({ detail: 'forbidden' }), { status: sessionsStatus });
            }
            return ok({ status: 'success', data: sessionsPayload });
        }
        if (url.includes('/api/assistants/101/day-status')) {
            return ok({ status: 'success', data: dayStatus });
        }
        if (url.includes('/api/assistants/101/sanctions/active')) {
            return ok({ status: 'success', data: sanctions });
        }
        if (url.endsWith('/api/assistants/101')) {
            return ok({ status: 'success', data: assistant });
        }
        if (url.endsWith('/api/assistants/202')) {
            return ok({ status: 'success', data: higherAssistant });
        }
        if (url.endsWith('/api/assistants')) {
            return ok({ status: 'success', data: [assistant, higherAssistant] });
        }
        if (url.endsWith('/api/assistants/101/session')) {
            return ok({ status: 'success', data: {} });
        }
        if (url.includes('/api/assistants/202/sessions')) {
            return ok({ status: 'success', data: [] });
        }
        if (url.includes('/api/assistants/202/day-status')) {
            return ok({ status: 'success', data: dayStatus });
        }
        if (url.includes('/api/assistants/202/sanctions/active')) {
            return ok({ status: 'success', data: [] });
        }
        if (url.endsWith('/api/admin/users/101/role')) {
            return ok({ status: 'success', data: {} });
        }
        if (url.endsWith('/api/admin/users/101/deactivate')) {
            return ok({ status: 'success', data: {} });
        }
        if (url.endsWith('/api/assistant-day-points')) {
            return ok({ status: 'success', data: {} });
        }
        if (url.endsWith('/api/assistant-day-mchat')) {
            return ok({ status: 'success', data: {} });
        }
        return new Response('{}', { status: 404 });
    });

describe('AssistantsManagement', () => {
    beforeEach(() => {
        vi.stubGlobal('localStorage', createLocalStorageMock());
        setAccessToken('test-token');
    });

    afterEach(() => {
        setAccessToken(null);
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('loads session targets from the dedicated endpoint and does not call streamers/events endpoints', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        render(<AssistantsManagement user={fullAccessUser} />);

        await waitFor(() => {
            expect(screen.getByText('Выберите стримера')).toBeInTheDocument();
        });

        expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/assistants/session-targets')).toBe(true);
        expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/streamers')).toBe(false);
        expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/events')).toBe(false);
    });

    it('renders higher-rank targets as read-only and does not expose lifecycle controls', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);
        const ui = userEvent.setup();

        render(<AssistantsManagement user={manageOnlyAssistantUser} />);

        await waitFor(() => {
            expect(screen.getByText('Ассистенты')).toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: /Boss/ }));

        await waitFor(() => {
            expect(
                screen.getByText('Эта учетная запись выше вашего уровня и доступна только для просмотра.'),
            ).toBeInTheDocument();
        });

        expect(screen.queryByRole('button', { name: 'Деактивировать' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Добавить ручную сессию' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Выдать санкцию' })).not.toBeInTheDocument();
    });

    it('renders sessions in read-only mode when user only has assistants.sessions.view', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        render(<AssistantsManagement user={readOnlySessionsUser} />);

        await waitFor(() => {
            expect(screen.getByText('Сессии ассистента')).toBeInTheDocument();
        });

        expect(screen.getByText('Read-only')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Редактировать' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Удалить' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Добавить ручную сессию' })).not.toBeInTheDocument();
    });

    it('does not fall back to spec sessions endpoint on 403', async () => {
        const fetchMock = createFetchMock({ sessionsStatus: 403 });
        vi.stubGlobal('fetch', fetchMock);

        render(<AssistantsManagement user={readOnlySessionsUser} />);

        await waitFor(() => {
            expect(screen.getByText('forbidden')).toBeInTheDocument();
        });

        expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/api/spec/sessions/'))).toBe(false);
    });

    it('shows active sanctions read-only without manual controls when user lacks sanctions.manage', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        render(<AssistantsManagement user={readOnlySessionsUser} />);

        await waitFor(() => {
            expect(screen.getByText('Активные санкции')).toBeInTheDocument();
        });

        expect(screen.getByText((content) => content.includes('12.03.2026'))).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Выдать санкцию' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Снять вручную' })).not.toBeInTheDocument();
    });

    it('requests workoff preview and renders leave-aware breakdown', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);
        const ui = userEvent.setup();

        render(<AssistantsManagement user={fullAccessUser} />);

        await waitFor(() => {
            expect(screen.getByText('Ручная санкция')).toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: '+ Добавить отработку' }));

        await waitFor(() => {
            expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/sanctions/workoff-preview')).toBe(true);
        });

        expect(screen.getByText('U/O не засчитываются и продлевают отработку.')).toBeInTheDocument();
        expect(screen.getAllByText('Дней по плану: 3').length).toBeGreaterThan(0);
        expect(screen.getAllByText('Эффективная дата окончания: 2026-03-24').length).toBeGreaterThan(0);

        await ui.click(screen.getByRole('button', { name: /Показать дни/i }));

        await waitFor(() => {
            expect(screen.getByRole('button', { name: 'Скрыть дни' })).toBeInTheDocument();
        });

        expect(screen.getAllByText('вручную: У').length).toBeGreaterThan(0);
    });
});
