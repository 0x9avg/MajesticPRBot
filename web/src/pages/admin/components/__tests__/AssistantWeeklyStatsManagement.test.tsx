import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { setAccessToken } from '../../../../api/client';
import AssistantWeeklyStatsManagement from '../AssistantWeeklyStatsManagement';

type StorageDict = Record<string, string>;
let writeTextMock: ReturnType<typeof vi.fn>;

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

const weekStart = '2026-03-16';
const weekEnd = '2026-03-22';

const makeDays = (manualStatus: string | null = null, autoAbsence = true) => ([
    {
        work_date: '2026-03-16',
        weekday_label: 'Пн',
        spec_hours_on_day: 4,
        mchat_count: 1,
        complaints_count: 0,
        manual_status: manualStatus,
        auto_status: null,
        resolved_status: manualStatus,
        status_source: manualStatus ? 'manual' : 'none',
    },
    {
        work_date: '2026-03-17',
        weekday_label: 'Вт',
        spec_hours_on_day: 5,
        mchat_count: 0,
        complaints_count: 1,
        manual_status: null,
        auto_status: autoAbsence ? 'P' : null,
        resolved_status: autoAbsence ? 'P' : null,
        status_source: autoAbsence ? 'auto' : 'none',
    },
    {
        work_date: '2026-03-18',
        weekday_label: 'Ср',
        spec_hours_on_day: 6,
        mchat_count: 2,
        complaints_count: 0,
        manual_status: null,
        auto_status: null,
        resolved_status: null,
        status_source: 'none',
    },
    {
        work_date: '2026-03-19',
        weekday_label: 'Чт',
        spec_hours_on_day: 4,
        mchat_count: 1,
        complaints_count: 0,
        manual_status: null,
        auto_status: null,
        resolved_status: null,
        status_source: 'none',
    },
    {
        work_date: '2026-03-20',
        weekday_label: 'Пт',
        spec_hours_on_day: 4,
        mchat_count: 0,
        complaints_count: 0,
        manual_status: null,
        auto_status: null,
        resolved_status: null,
        status_source: 'none',
    },
    {
        work_date: '2026-03-21',
        weekday_label: 'Сб',
        spec_hours_on_day: 4,
        mchat_count: 0,
        complaints_count: 0,
        manual_status: null,
        auto_status: null,
        resolved_status: null,
        status_source: 'none',
    },
    {
        work_date: '2026-03-22',
        weekday_label: 'Вс',
        spec_hours_on_day: 4,
        mchat_count: 0,
        complaints_count: 0,
        manual_status: null,
        auto_status: null,
        resolved_status: null,
        status_source: 'none',
    },
]);

const assistantOne = {
    assistant_id: '101',
    nickname: 'Tester',
    role: 'employee',
    week_start: weekStart,
    week_end: weekEnd,
    days: makeDays(null, true),
    total_spec_hours: 31,
    total_mchat: 4,
    total_complaints: 1,
    suggested_result: 'Актив',
    selected_result: null,
    result_display: 'Актив',
    count_P: 1,
    count_U: 0,
    count_O: 0,
    payout_type: null,
    payout_server: null,
    payout_static: null,
    payout_issue_status: 'pending',
    payout_issued_at: null,
    payout_issued_by_id: null,
    generated_payout_command: null,
    generated_payout_available: false,
    generated_payout_reason: 'Заполни payout type, server, static и selected result',
};

const assistantTwo = {
    assistant_id: '102',
    nickname: 'Helper',
    role: 'senior_employee',
    week_start: weekStart,
    week_end: weekEnd,
    days: makeDays('U', false),
    total_spec_hours: 28,
    total_mchat: 2,
    total_complaints: 0,
    suggested_result: 'Инактив/Актив',
    selected_result: 'Актив',
    result_display: 'Актив',
    count_P: 0,
    count_U: 1,
    count_O: 0,
    payout_type: 'MC',
    payout_server: 'RU2',
    payout_static: 'static',
    payout_issue_status: 'pending',
    payout_issued_at: null,
    payout_issued_by_id: null,
    generated_payout_command: 'RU2:givedonate static 1200 pr-assist_byStynee',
    generated_payout_available: true,
    generated_payout_reason: null,
};

const assistantThree = {
    assistant_id: '103',
    nickname: 'Closer',
    role: 'employee',
    week_start: weekStart,
    week_end: weekEnd,
    days: makeDays(null, false),
    total_spec_hours: 30,
    total_mchat: 5,
    total_complaints: 2,
    suggested_result: 'Актив',
    selected_result: 'Актив',
    result_display: 'Актив',
    count_P: 0,
    count_U: 0,
    count_O: 0,
    payout_type: 'Premium',
    payout_server: 'RU7',
    payout_static: 'static',
    payout_issue_status: 'issued',
    payout_issued_at: '2026-03-19T14:45:00',
    payout_issued_by_id: '7',
    generated_payout_command: 'RU7:setvip static 7 pr-assist_byStynee',
    generated_payout_available: true,
    generated_payout_reason: null,
};

const adminPayload = {
    week_start: weekStart,
    week_end: weekEnd,
    day_labels: makeDays(null, false).map((day) => ({ work_date: day.work_date, label: day.weekday_label })),
    items: [assistantOne, assistantTwo, assistantThree],
    payout_types: [
        { value: 'EXP', label: 'EXP' },
        { value: 'Premium', label: 'Premium' },
        { value: 'MC', label: 'MC' },
        { value: 'MONEY', label: 'MONEY' },
    ],
    payout_servers: ['RU10', 'RU2', 'RU1', 'RU3'],
    result_options: ['Ультра-Актив', 'Актив', 'Актив/Отпуск', 'Инактив', 'Инактив/Отпуск', 'Отпуск', 'Инактив/Актив'],
};

const ok = (payload: unknown) =>
    new Response(JSON.stringify({ status: 'success', data: payload }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
    });

const createFetchMock = () =>
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = (init?.method ?? 'GET').toUpperCase();

        if (url === `/api/assistant-weekly/admin?week_start=${weekStart}`) {
            return ok(adminPayload);
        }

        if (url === `/api/assistant-weekly/admin/101?week_start=${weekStart}` && method === 'PUT') {
            return ok({
                ...assistantOne,
                days: makeDays('P'),
                selected_result: 'Актив',
                payout_type: 'EXP',
                payout_server: 'RU1',
                payout_static: 'static',
                payout_issue_status: 'pending',
                payout_issued_at: null,
                payout_issued_by_id: null,
                generated_payout_command: 'RU1:giveexp static 35000 pr-assist_byStynee',
                generated_payout_available: true,
                generated_payout_reason: null,
            });
        }

        if (url === `/api/assistant-weekly/admin/102/payout-issue?week_start=${weekStart}` && method === 'PUT') {
            return ok({
                ...assistantTwo,
                payout_issue_status: 'issued',
                payout_issued_at: '2026-03-19T15:00:00',
                payout_issued_by_id: '1',
            });
        }

        if (url === `/api/assistant-weekly/admin/103/payout-issue?week_start=${weekStart}` && method === 'PUT') {
            return ok({
                ...assistantThree,
                payout_issue_status: 'pending',
                payout_issued_at: null,
                payout_issued_by_id: null,
            });
        }

        if (url === `/api/assistant-weekly/admin/103?week_start=${weekStart}` && method === 'PUT') {
            return ok({
                ...assistantThree,
                payout_server: 'RU3',
                payout_issue_status: 'pending',
                payout_issued_at: null,
                payout_issued_by_id: null,
                generated_payout_command: 'RU3:setvip static 7 pr-assist_byStynee',
            });
        }

        return new Response('{}', { status: 404 });
    });

describe('AssistantWeeklyStatsManagement', () => {
    beforeEach(() => {
        vi.stubGlobal('localStorage', createLocalStorageMock());
        writeTextMock = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: {
                writeText: writeTextMock,
            },
        });
        setAccessToken('test-token');
    });

    afterEach(() => {
        setAccessToken(null);
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('renders the admin weekly table and filters rows by search', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);
        const ui = userEvent.setup();

        render(<AssistantWeeklyStatsManagement />);

        await waitFor(() => {
            expect(screen.getByText('Недельная статистика ассистентов')).toBeInTheDocument();
        });

        expect(screen.getByText('Tester')).toBeInTheDocument();
        expect(screen.getByText('Helper')).toBeInTheDocument();
        expect(screen.getByText('16.03 - 22.03')).toBeInTheDocument();

        await waitFor(() => {
            const payoutServerSelect = screen.getByLabelText('Payout server Tester') as HTMLSelectElement;
            expect(Array.from(payoutServerSelect.options).map((option) => option.text)).toEqual(['Сервер', 'RU1', 'RU2', 'RU3', 'RU10']);
        });

        const testerTuesdayStatus = screen.getByLabelText('Статус дня Tester Вт') as HTMLSelectElement;
        expect(testerTuesdayStatus.value).toBe('inherit');
        expect(Array.from(testerTuesdayStatus.options).map((option) => option.text)).toContain('Авто: П');

        await ui.type(screen.getByPlaceholderText('Поиск по нику'), 'helper');

        await waitFor(() => {
            expect(screen.queryByText('Tester')).not.toBeInTheDocument();
            expect(screen.getByText('Helper')).toBeInTheDocument();
        });
    });

    it('hides empty status badges and applies weekly review filters', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);
        const ui = userEvent.setup();

        render(<AssistantWeeklyStatsManagement />);

        await waitFor(() => {
            expect(screen.getByText('Tester')).toBeInTheDocument();
            expect(screen.getByText('Helper')).toBeInTheDocument();
            expect(screen.getByText('Closer')).toBeInTheDocument();
        });

        expect(screen.queryByText('—', { selector: 'span' })).not.toBeInTheDocument();

        await ui.click(screen.getByRole('button', { name: /Есть П \/ У \/ О/ }));
        await waitFor(() => {
            expect(screen.getByText('Tester')).toBeInTheDocument();
            expect(screen.getByText('Helper')).toBeInTheDocument();
            expect(screen.queryByText('Closer')).not.toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: /Черновики/ }));
        await waitFor(() => {
            expect(screen.getByText('Ничего не найдено')).toBeInTheDocument();
            expect(screen.queryByText('Tester')).not.toBeInTheDocument();
            expect(screen.queryByText('Helper')).not.toBeInTheDocument();
            expect(screen.queryByText('Closer')).not.toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: /Без итогового решения/ }));
        await waitFor(() => {
            expect(screen.getByText('Tester')).toBeInTheDocument();
            expect(screen.queryByText('Helper')).not.toBeInTheDocument();
            expect(screen.queryByText('Closer')).not.toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: /Готово к выдаче/ }));
        await waitFor(() => {
            expect(screen.queryByText('Tester')).not.toBeInTheDocument();
            expect(screen.getByText('Helper')).toBeInTheDocument();
            expect(screen.queryByText('Closer')).not.toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: /Выдано/ }));
        await waitFor(() => {
            expect(screen.queryByText('Tester')).not.toBeInTheDocument();
            expect(screen.queryByText('Helper')).not.toBeInTheDocument();
            expect(screen.getByText('Closer')).toBeInTheDocument();
        });
    });

    it('edits inline fields, keeps command stale until save, and sends row payload', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);
        const ui = userEvent.setup();

        render(<AssistantWeeklyStatsManagement />);

        await waitFor(() => {
            expect(screen.getByLabelText('Статус дня Tester Пн')).toBeInTheDocument();
        });

        await ui.selectOptions(screen.getByLabelText('Статус дня Tester Пн'), 'P');
        await ui.selectOptions(screen.getByLabelText('Selected result Tester'), 'Актив');
        await ui.selectOptions(screen.getByLabelText('Payout type Tester'), 'EXP');
        await ui.selectOptions(screen.getByLabelText('Payout server Tester'), 'RU1');
        await ui.clear(screen.getByLabelText('Payout static Tester'));
        await ui.type(screen.getByLabelText('Payout static Tester'), 'static');

        expect(screen.getByText('Сохрани изменения для генерации команды')).toBeInTheDocument();

        await ui.click(screen.getByRole('button', { name: 'Сохранить Tester' }));

        await waitFor(() => {
            const putCall = fetchMock.mock.calls.find(([requestUrl, requestInit]) => (
                String(requestUrl) === `/api/assistant-weekly/admin/101?week_start=${weekStart}`
                && (requestInit as RequestInit | undefined)?.method === 'PUT'
            ));
            expect(putCall).toBeTruthy();
        });

        const putCall = fetchMock.mock.calls.find(([requestUrl, requestInit]) => (
            String(requestUrl) === `/api/assistant-weekly/admin/101?week_start=${weekStart}`
            && (requestInit as RequestInit | undefined)?.method === 'PUT'
        ));
        const body = JSON.parse(String((putCall?.[1] as RequestInit | undefined)?.body ?? '{}')) as {
            selected_result: string;
            payout_type: string;
            payout_server: string;
            payout_static: string;
            day_overrides: Array<{ work_date: string; manual_status: string | null; is_manual_override: boolean }>;
        };

        expect(body.selected_result).toBe('Актив');
        expect(body.payout_type).toBe('EXP');
        expect(body.payout_server).toBe('RU1');
        expect(body.payout_static).toBe('static');
        expect(body.day_overrides[0]).toEqual({ work_date: '2026-03-16', manual_status: 'P', is_manual_override: true });

        await waitFor(() => {
            expect(screen.getByText('RU1:giveexp static 35000 pr-assist_byStynee')).toBeInTheDocument();
        });

        const copyButton = screen.getByRole('button', { name: 'Скопировать команду Tester' });
        expect(copyButton).not.toBeDisabled();
    });

    it('marks payout as issued and allows undo via dedicated issuance endpoint', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);
        const ui = userEvent.setup();

        render(<AssistantWeeklyStatsManagement />);

        await waitFor(() => {
            expect(screen.getByRole('button', { name: 'Отметить выдано Helper' })).toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: 'Отметить выдано Helper' }));

        await waitFor(() => {
            const issueCall = fetchMock.mock.calls.find(([requestUrl, requestInit]) => (
                String(requestUrl) === `/api/assistant-weekly/admin/102/payout-issue?week_start=${weekStart}`
                && (requestInit as RequestInit | undefined)?.method === 'PUT'
            ));
            expect(issueCall).toBeTruthy();
        });

        const issueCall = fetchMock.mock.calls.find(([requestUrl, requestInit]) => (
            String(requestUrl) === `/api/assistant-weekly/admin/102/payout-issue?week_start=${weekStart}`
            && (requestInit as RequestInit | undefined)?.method === 'PUT'
        ));
        expect(JSON.parse(String((issueCall?.[1] as RequestInit | undefined)?.body ?? '{}'))).toEqual({ status: 'issued' });

        await waitFor(() => {
            expect(screen.getByRole('button', { name: 'Снять выдачу Helper' })).toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: 'Снять выдачу Closer' }));

        await waitFor(() => {
            const undoCall = fetchMock.mock.calls.find(([requestUrl, requestInit]) => (
                String(requestUrl) === `/api/assistant-weekly/admin/103/payout-issue?week_start=${weekStart}`
                && (requestInit as RequestInit | undefined)?.method === 'PUT'
            ));
            expect(undoCall).toBeTruthy();
            expect(screen.getByRole('button', { name: 'Отметить выдано Closer' })).toBeInTheDocument();
        });
    });

    it('warns that issued payout will reset after payout edits and returns row to ready state after save', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);
        const ui = userEvent.setup();

        render(<AssistantWeeklyStatsManagement />);

        await waitFor(() => {
            expect(screen.getByRole('button', { name: 'Снять выдачу Closer' })).toBeInTheDocument();
        });

        await ui.selectOptions(screen.getByLabelText('Payout server Closer'), 'RU3');

        expect(screen.getByText('После сохранения отметка выдачи будет снята')).toBeInTheDocument();

        await ui.click(screen.getByRole('button', { name: 'Сохранить Closer' }));

        await waitFor(() => {
            expect(screen.getByRole('button', { name: 'Отметить выдано Closer' })).toBeInTheDocument();
            expect(screen.queryByText('После сохранения отметка выдачи будет снята')).not.toBeInTheDocument();
        });
    });

    it('allows manual clear of auto absence and persists explicit manual override', async () => {
        const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
            const url = String(input);
            const method = (init?.method ?? 'GET').toUpperCase();

            if (url === `/api/assistant-weekly/admin?week_start=${weekStart}`) {
                return ok(adminPayload);
            }

            if (url === `/api/assistant-weekly/admin/101?week_start=${weekStart}` && method === 'PUT') {
                return ok({
                    ...assistantOne,
                    days: assistantOne.days.map((day, index) => (
                        index === 1
                            ? {
                                ...day,
                                manual_status: null,
                                auto_status: 'P',
                                resolved_status: null,
                                status_source: 'manual',
                            }
                            : day
                    )),
                    count_P: 0,
                    count_U: 0,
                    count_O: 0,
                });
            }

            return new Response('{}', { status: 404 });
        });
        vi.stubGlobal('fetch', fetchMock);
        const ui = userEvent.setup();

        render(<AssistantWeeklyStatsManagement />);

        const tuesdayStatus = await screen.findByLabelText('Статус дня Tester Вт');
        await ui.selectOptions(tuesdayStatus, 'clear');
        await ui.click(screen.getByRole('button', { name: 'Сохранить Tester' }));

        await waitFor(() => {
            const putCall = fetchMock.mock.calls.find(([requestUrl, requestInit]) => (
                String(requestUrl) === `/api/assistant-weekly/admin/101?week_start=${weekStart}`
                && (requestInit as RequestInit | undefined)?.method === 'PUT'
            ));
            expect(putCall).toBeTruthy();
        });

        const putCall = fetchMock.mock.calls.find(([requestUrl, requestInit]) => (
            String(requestUrl) === `/api/assistant-weekly/admin/101?week_start=${weekStart}`
            && (requestInit as RequestInit | undefined)?.method === 'PUT'
        ));
        const body = JSON.parse(String((putCall?.[1] as RequestInit | undefined)?.body ?? '{}')) as {
            day_overrides: Array<{ work_date: string; manual_status: string | null; is_manual_override: boolean }>;
        };

        expect(body.day_overrides[1]).toEqual({
            work_date: '2026-03-17',
            manual_status: null,
            is_manual_override: true,
        });

        await waitFor(() => {
            expect(screen.getByLabelText('Статус дня Tester Вт')).toHaveValue('clear');
        });
    });
});
