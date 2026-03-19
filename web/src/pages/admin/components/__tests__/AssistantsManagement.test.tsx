import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AssistantsManagement from '../AssistantsManagement';
import { setAccessToken } from '../../../../api/client';

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

const ok = (payload: unknown) =>
    new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
    });

const createFetchMock = () =>
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
        if (url.includes('/api/assistants/101/sessions')) {
            return ok({ status: 'success', data: [] });
        }
        if (url.includes('/api/assistants/101/day-status')) {
            return ok({
                status: 'success',
                data: {
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
                },
            });
        }
        if (url.includes('/api/assistants/101/sanctions/active')) {
            return ok({
                status: 'success',
                data: [
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
                ],
            });
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
        if (url.endsWith('/api/assistants/101/session')) {
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

    it('shows selectors for streamers and events in add form', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        const user = userEvent.setup();
        render(<AssistantsManagement />);

        await waitFor(() => {
            expect(screen.getByText('Выберите стримера')).toBeInTheDocument();
        });

        await user.click(screen.getAllByText('Стример')[0]);
        await user.click(screen.getByText('Событие'));

        await waitFor(() => {
            expect(screen.getByText('Выберите событие')).toBeInTheDocument();
        });
    });

    it('shows after-sanctions totals in assistant metrics', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        render(<AssistantsManagement />);

        await waitFor(() => {
            expect(screen.getByText('Баллы после санкций')).toBeInTheDocument();
        });

        expect(screen.getAllByText('9.5').length).toBeGreaterThanOrEqual(2);
        expect(screen.getByText('Баллы после санкций')).toBeInTheDocument();
    });

    it('uses display_issued_at for active sanctions and hides amount for check', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        const user = userEvent.setup();
        render(<AssistantsManagement />);

        await waitFor(() => {
            expect(screen.getByText('Ручная санкция')).toBeInTheDocument();
        });

        expect(screen.queryByText('Размер')).toBeInTheDocument();

        await user.click(screen.getByText('Штрафной балл'));
        await user.click(screen.getByText('Галка'));

        expect(screen.queryByText('Размер')).not.toBeInTheDocument();

        await user.click(screen.getByText('Галка'));
        await user.click(screen.getByText('Устный'));

        await waitFor(() => {
            expect(screen.getByText('Дата автоснятия')).toBeInTheDocument();
        });

        await user.click(screen.getByRole('button', { name: 'Выдать санкцию' }));

        await waitFor(() => {
            expect(screen.getByText('Укажите дату автоснятия для устного или строгого наказания')).toBeInTheDocument();
        });

        expect(screen.getByText((content) => content.includes('12.03.2026'))).toBeInTheDocument();
        expect(screen.queryByText((content) => content.includes('10.03.2026'))).not.toBeInTheDocument();
        expect(screen.getByText('Автоснятие: 2026-03-20')).toBeInTheDocument();
        expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/assistant-sanctions')).toBe(false);
    });

    it('keeps manual mode and allows session without comment', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        const user = userEvent.setup();
        render(<AssistantsManagement />);

        await waitFor(() => {
            expect(screen.getByText('Выберите стримера')).toBeInTheDocument();
        });

        await user.click(screen.getAllByText('Стример')[0]);
        await user.click(screen.getByText('Manual'));

        await user.click(screen.getByRole('button', { name: 'Добавить ручную сессию' }));

        await waitFor(() => {
            expect(screen.queryByText('Для manual-сессии обязателен комментарий')).not.toBeInTheDocument();
            expect(screen.getByText('Изменения сохранены')).toBeInTheDocument();
        });

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/assistants/101/session',
            expect.objectContaining({ method: 'POST' })
        );
    });

    it('saves day-based point adjustments via sanctions API', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        const user = userEvent.setup();
        render(<AssistantsManagement />);

        await waitFor(() => {
            expect(screen.getByPlaceholderText('На сколько изменить корректировку')).toBeInTheDocument();
        });

        await user.type(screen.getByPlaceholderText('На сколько изменить корректировку'), '1.5');
        await user.click(screen.getByRole('button', { name: 'Сохранить корректировку баллов' }));

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalledWith(
                '/api/assistant-day-points',
                expect.objectContaining({ method: 'POST' })
            );
        });

        const mutationCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/assistant-day-points');
        expect(mutationCall).toBeTruthy();
        expect(JSON.parse(String((mutationCall?.[1] as RequestInit | undefined)?.body))).toMatchObject({
            assistant_id: '101',
            delta_points: 1.5,
        });
    });

    it('saves day-based mchat via sanctions API', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        const user = userEvent.setup();
        render(<AssistantsManagement />);

        await waitFor(() => {
            expect(screen.getByPlaceholderText('Введите итоговое количество MChat')).toBeInTheDocument();
        });

        await user.type(screen.getByPlaceholderText('Введите итоговое количество MChat'), '7');
        await user.click(screen.getByRole('button', { name: 'Сохранить MChat за день' }));

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalledWith(
                '/api/assistant-day-mchat',
                expect.objectContaining({ method: 'PUT' })
            );
        });

        const mutationCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/assistant-day-mchat');
        expect(mutationCall).toBeTruthy();
        expect(JSON.parse(String((mutationCall?.[1] as RequestInit | undefined)?.body))).toMatchObject({
            assistant_id: '101',
            mchat_count: 7,
        });
    });

    it('fetches and renders manual workoff preview with daily leave-aware breakdown', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        const user = userEvent.setup();
        render(<AssistantsManagement />);

        await waitFor(() => {
            expect(screen.getByText('Ручная санкция')).toBeInTheDocument();
        });

        await user.click(screen.getByRole('button', { name: '+ Добавить отработку' }));

        await waitFor(() => {
            expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/sanctions/workoff-preview')).toBe(true);
        });

        await waitFor(() => {
            expect(screen.getByText('Предпросмотр отработки')).toBeInTheDocument();
        });

        expect(screen.getByText('U/O не засчитываются и продлевают отработку.')).toBeInTheDocument();
        expect(screen.getAllByText('Дней по плану: 3').length).toBeGreaterThan(0);
        expect(screen.getAllByText('Эффективная дата окончания: 2026-03-24').length).toBeGreaterThan(0);
        const manualLabelsBeforeExpand = screen.queryAllByText('вручную: У').length;
        await user.click(screen.getByRole('button', { name: /Показать дни/i }));
        await waitFor(() => {
            expect(screen.getByRole('button', { name: 'Скрыть дни' })).toBeInTheDocument();
        });
        expect(screen.queryAllByText('вручную: У').length).toBeGreaterThan(manualLabelsBeforeExpand);
    });

    it('renders daily workoff progress in active sanctions', async () => {
        const fetchMock = createFetchMock();
        vi.stubGlobal('fetch', fetchMock);

        render(<AssistantsManagement />);

        await waitFor(() => {
            expect(screen.getByText('Активные санкции')).toBeInTheDocument();
        });

        await waitFor(() => {
            expect(screen.getAllByText('План: 3').length).toBeGreaterThan(0);
        });

        expect(screen.getAllByText('Учтено: 2').length).toBeGreaterThan(0);
        expect(screen.getAllByText('Эффективная дата конца: 2026-03-24').length).toBeGreaterThan(0);
        expect(screen.getAllByText('вручную: У').length).toBeGreaterThan(0);
    });
});
