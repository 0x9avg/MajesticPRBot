import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UserContext } from '../../../types/auth';

let mockedUser: UserContext | null = null;
const navigateMock = vi.fn();

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
    return {
        ...actual,
        useOutletContext: () => ({ user: mockedUser }),
        useNavigate: () => navigateMock,
    };
});

import ComplaintsPage from '../ComplaintsPage';

const gameServers = Array.from({ length: 18 }, (_, index) => {
    const id = index + 1;
    return {
        id,
        full_name: `Majestic #${id}`,
        short_name: `#${id}`,
        command_name: `RU${id}`,
        sort_order: id,
        is_active: id !== 14,
    };
});

const queueComplaints = [
    {
        id: 'c1',
        complaint_id: 'c1',
        assistant_id: '1001',
        assistant_name: 'Tester',
        created_by_id: '1001',
        created_by_name: 'Tester',
        server: 7,
        media: 'Ник',
        complaint_link: 'https://discord.com/channels/test/complaint',
        incident_at: '2026-03-20T10:15:00',
        created_at: '2026-03-20T10:20:00',
        reviewed_at: null,
        issued_at: null,
        status: 'draft',
        status_label: 'Черновик',
        punishments_count: 2,
        aggregate_command:
            '/mute 138254 30 Тестовая причина 1 (media-жалоба Ник | 10:15 20.03) by Tester\n'
            + '/warn 50001 Тестовая причина 2 (media-жалоба Ник | 10:15 20.03) by Tester',
        aggregate_message:
            'Игрок #138254 получил Mute на 30 минут за Тестовая причина 1\n'
            + 'Игрок #50001 получил Warn за Тестовая причина 2',
        can_edit: true,
        can_delete: true,
        can_submit: true,
        can_issue: false,
        punishments: [
            {
                id: 'p1',
                complaint_id: 'c1',
                punishment_type: 'mute',
                static: 138254,
                duration: 30,
                reason: 'Тестовая причина 1',
                command: '/mute 138254 30 Тестовая причина 1 (media-жалоба Ник | 10:15 20.03) by Tester',
                message: 'Игрок #138254 получил Mute на 30 минут за Тестовая причина 1',
            },
            {
                id: 'p2',
                complaint_id: 'c1',
                punishment_type: 'warn',
                static: 50001,
                duration: null,
                reason: 'Тестовая причина 2',
                command: '/warn 50001 Тестовая причина 2 (media-жалоба Ник | 10:15 20.03) by Tester',
                message: 'Игрок #50001 получил Warn за Тестовая причина 2',
            },
        ],
    },
    {
        id: 'c2',
        complaint_id: 'c2',
        assistant_id: '1001',
        assistant_name: 'Tester',
        created_by_id: '1001',
        created_by_name: 'Tester',
        server: 14,
        media: 'snikers',
        complaint_link: 'https://discord.com/channels/test/complaint2',
        incident_at: '2026-03-20T09:15:00',
        created_at: '2026-03-20T09:20:00',
        reviewed_at: '2026-03-20T09:30:00',
        issued_at: null,
        status: 'pending',
        status_label: 'К выдаче',
        punishments_count: 1,
        aggregate_command: '/ajail 27253 10 Готово к выдаче (media-жалоба snikers | 09:15 20.03) by Tester',
        aggregate_message: 'Игрок #27253 получил Ajail на 10 минут за Готово к выдаче',
        can_edit: true,
        can_delete: true,
        can_submit: false,
        can_issue: true,
        punishments: [
            {
                id: 'p4',
                complaint_id: 'c2',
                punishment_type: 'ajail',
                static: 27253,
                duration: 10,
                reason: 'Готово к выдаче',
                command: '/ajail 27253 10 Готово к выдаче (media-жалоба snikers | 09:15 20.03) by Tester',
                message: 'Игрок #27253 получил Ajail на 10 минут за Готово к выдаче',
            },
        ],
    },
    {
        id: 'c3',
        complaint_id: 'c3',
        assistant_id: '1001',
        assistant_name: 'Tester',
        created_by_id: '1001',
        created_by_name: 'Tester',
        server: 2,
        media: 'gamma',
        complaint_link: '',
        incident_at: '2026-03-20T11:00:00',
        created_at: '2026-03-20T11:05:00',
        reviewed_at: null,
        issued_at: null,
        status: 'draft',
        status_label: 'Черновик',
        punishments_count: 1,
        aggregate_command: '/ban 99999 3 Одна причина (media-жалоба gamma | 11:00 20.03) by Tester',
        aggregate_message: 'Игрок #99999 получил Ban на 3 дней за Одна причина',
        can_edit: true,
        can_delete: true,
        can_submit: true,
        can_issue: false,
        punishments: [
            {
                id: 'p3',
                complaint_id: 'c3',
                punishment_type: 'ban',
                static: 99999,
                duration: 3,
                reason: 'Одна причина',
                command: '/ban 99999 3 Одна причина (media-жалоба gamma | 11:00 20.03) by Tester',
                message: 'Игрок #99999 получил Ban на 3 дней за Одна причина',
            },
        ],
    },
];

const historyComplaints = [
    {
        id: 'c4',
        complaint_id: 'c4',
        assistant_id: '1001',
        assistant_name: 'Tester',
        created_by_id: '1001',
        created_by_name: 'Tester',
        issued_by_id: '2002',
        issued_by_name: 'Admin',
        server: 5,
        media: 'history',
        complaint_link: 'https://discord.com/channels/test/history',
        incident_at: '2026-03-19T08:00:00',
        created_at: '2026-03-19T08:10:00',
        reviewed_at: '2026-03-19T09:00:00',
        issued_at: '2026-03-19T10:00:00',
        status: 'issued',
        status_label: 'Выдано',
        punishments_count: 1,
        aggregate_command: '/hardban 44444 2 История (media-жалоба history | 08:00 19.03) by Admin',
        aggregate_message: 'Игрок #44444 получил HardBan на 2 дней за История',
        can_edit: false,
        can_delete: false,
        can_submit: false,
        can_issue: false,
        punishments: [
            {
                id: 'p6',
                complaint_id: 'c4',
                punishment_type: 'hardban',
                static: 44444,
                duration: 2,
                reason: 'История',
                command: '/hardban 44444 2 История (media-жалоба history | 08:00 19.03) by Admin',
                message: 'Игрок #44444 получил HardBan на 2 дней за История',
            },
        ],
    },
];

const detailById = {
    c1: {
        complaint: queueComplaints[0],
        punishments: queueComplaints[0].punishments,
        aggregate_command: queueComplaints[0].aggregate_command,
        aggregate_message: queueComplaints[0].aggregate_message,
    },
    c2: {
        complaint: queueComplaints[1],
        punishments: queueComplaints[1].punishments,
        aggregate_command: queueComplaints[1].aggregate_command,
        aggregate_message: queueComplaints[1].aggregate_message,
    },
    c3: {
        complaint: queueComplaints[2],
        punishments: queueComplaints[2].punishments,
        aggregate_command: queueComplaints[2].aggregate_command,
        aggregate_message: queueComplaints[2].aggregate_message,
    },
};

const createFetchMock = () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method || 'GET';

        if (url.includes('/api/game-servers')) {
            return new Response(JSON.stringify({ status: 'success', data: gameServers }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        if (url.includes('/api/complaints/queue')) {
            return new Response(JSON.stringify({ status: 'success', data: queueComplaints }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        if (url.includes('/api/complaints/history')) {
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: {
                        items: historyComplaints,
                        total: 1,
                        page: 1,
                        pages: 1,
                    },
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } },
            );
        }

        if (url.includes('/api/complaints/c1') && method === 'GET') {
            return new Response(JSON.stringify({ status: 'success', data: detailById.c1 }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        if (url.includes('/api/complaints/c2') && method === 'GET') {
            return new Response(JSON.stringify({ status: 'success', data: detailById.c2 }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        if (url.includes('/api/complaints/c3') && method === 'GET') {
            return new Response(JSON.stringify({ status: 'success', data: detailById.c3 }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        if (url.includes('/api/complaints/c2/issue') && method === 'POST') {
            return new Response(JSON.stringify({ status: 'success', data: {} }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        if (url.includes('/api/complaints/c1') && method === 'PATCH') {
            return new Response(JSON.stringify({ status: 'success', data: detailById.c1 }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        if (url.includes('/api/complaints/c3') && method === 'DELETE') {
            return new Response(JSON.stringify({ status: 'success', data: {} }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        if (url.includes('/api/complaints/c1') && method === 'DELETE') {
            return new Response(JSON.stringify({ status: 'success', data: {} }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        if (url.includes('/api/complaints') && method === 'POST') {
            return new Response(JSON.stringify({ status: 'success', data: { id: 'c99' } }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        return new Response('{}', { status: 404 });
    });

    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
};

describe('ComplaintsPage', () => {
    beforeEach(() => {
        navigateMock.mockReset();
        mockedUser = {
            id: '1',
            discord_id: '1001',
            username: 'tester',
            nickname: 'Tester',
            role: 'manager',
            require_password_change: false,
            permissions: {
                'complaints.queue.view': true,
                'complaints.create': true,
                'complaints.issue': true,
                'complaints.history.view': true,
                'complaints.manage.self': true,
                'complaints.manage.any': true,
            },
        };
    });

    it('renders complaint-level queue and history rows with aggregate previews', async () => {
        createFetchMock();
        const ui = userEvent.setup();

        render(<ComplaintsPage />);

        await waitFor(() => {
            expect(screen.getByText('Жалоба #c1')).toBeInTheDocument();
        });

        expect(screen.getAllByText('Жалоба #c1')).toHaveLength(1);
        const draftRow = screen.getByText('Жалоба #c1').closest('tr');
        expect(draftRow).toBeTruthy();
        expect(within(draftRow as HTMLElement).getByText('Ник')).toBeInTheDocument();
        expect(within(draftRow as HTMLElement).getByText(/\/mute 138254 30 Тестовая причина 1/)).toBeInTheDocument();
        expect(within(draftRow as HTMLElement).getByText(/Игрок #50001 получил Warn за Тестовая причина 2/)).toBeInTheDocument();
        expect(within(draftRow as HTMLElement).getByRole('button', { name: 'Отправить к выдаче' })).toBeInTheDocument();

        await ui.click(screen.getByRole('button', { name: 'История' }));

        await waitFor(() => {
            expect(screen.getByText('Жалоба #c4')).toBeInTheDocument();
        });
        expect(screen.getAllByText('Жалоба #c4')).toHaveLength(1);
    });

    it('opens history by default for history-only users and skips queue request', async () => {
        const fetchMock = createFetchMock();
        mockedUser = {
            id: '2',
            discord_id: '2001',
            username: 'auditor',
            nickname: 'Auditor',
            role: 'employee',
            require_password_change: false,
            permissions: {
                'complaints.history.view': true,
            },
        };

        render(<ComplaintsPage />);

        await waitFor(() => {
            expect(screen.getByText('Жалоба #c4')).toBeInTheDocument();
        });

        expect(screen.queryByRole('button', { name: 'К выдаче' })).not.toBeInTheDocument();
        expect(fetchMock.mock.calls.some(([requestUrl]) => String(requestUrl).includes('/api/complaints/queue'))).toBe(false);
        expect(fetchMock.mock.calls.some(([requestUrl]) => String(requestUrl).includes('/api/complaints/history'))).toBe(true);
    });

    it('creates complaint with single-line media input and aggregate previews', async () => {
        const fetchMock = createFetchMock();
        const ui = userEvent.setup();

        render(<ComplaintsPage />);

        await waitFor(() => {
            expect(screen.getByRole('button', { name: 'Создать жалобу' })).toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: 'Создать жалобу' }));

        const mediaInput = screen.getByLabelText('Медиа');
        expect(mediaInput.tagName).toBe('INPUT');

        await ui.type(screen.getByLabelText('Дата и время нарушения'), '2026-03-20T12:00');
        await ui.type(screen.getByPlaceholderText('https://...'), 'https://discord.com/channels/test/new');
        await ui.type(mediaInput, 'Ник');

        const staticInputs = screen.getAllByPlaceholderText('Static');
        const reasonInputs = screen.getAllByPlaceholderText('Причина наказания');
        const durationInputs = screen.getAllByPlaceholderText('30');

        await ui.type(staticInputs[0], '138254');
        await ui.type(durationInputs[0], '30');
        await ui.type(reasonInputs[0], 'Первое наказание');

        await ui.click(screen.getByRole('button', { name: 'Добавить наказание' }));

        const updatedStaticInputs = screen.getAllByPlaceholderText('Static');
        const updatedReasonInputs = screen.getAllByPlaceholderText('Причина наказания');
        const updatedDurationInputs = screen.getAllByPlaceholderText('30');

        await ui.type(updatedStaticInputs[1], '50001');
        await ui.type(updatedDurationInputs[1], '45');
        await ui.type(updatedReasonInputs[1], 'Второе наказание');

        expect(screen.getByText(/media-жалоба Ник \| 12:00 20.03/)).toBeInTheDocument();
        expect(screen.getByText(/Игрок #138254 получил Mute на 30 минут за Первое наказание/)).toBeInTheDocument();
        expect(screen.getByText(/Игрок #50001 получил Mute на 45 минут за Второе наказание/)).toBeInTheDocument();

        await ui.click(screen.getByRole('button', { name: 'Сохранить как черновик' }));

        await waitFor(() => {
            const postCall = fetchMock.mock.calls.find(
                ([requestUrl, requestInit]) =>
                    String(requestUrl).includes('/api/complaints')
                    && (requestInit as RequestInit | undefined)?.method === 'POST',
            );

            expect(postCall).toBeTruthy();
            const body = JSON.parse(String((postCall?.[1] as RequestInit).body));
            expect(body).toMatchObject({
                server: 1,
                target_status: 'draft',
                media: 'Ник',
                complaint_link: 'https://discord.com/channels/test/new',
                incident_at: '2026-03-20T12:00',
            });
            expect(body.punishments).toHaveLength(2);
        });
    });

    it('filters complaint history by server and keeps inactive server visible in edit mode', async () => {
        const fetchMock = createFetchMock();
        const ui = userEvent.setup();

        render(<ComplaintsPage />);

        await waitFor(() => {
            expect(screen.getByText('Жалоба #c1')).toBeInTheDocument();
        });

        const pendingRow = screen.getByText('Жалоба #c2').closest('tr');
        expect(pendingRow).toBeTruthy();
        await ui.click(within(pendingRow as HTMLElement).getByTitle('Редактировать'));

        await waitFor(() => {
            expect(screen.getAllByText('Majestic #14 (неактивен)').length).toBeGreaterThan(0);
        });

        await ui.click(screen.getByRole('button', { name: 'Закрыть' }));

        await ui.click(screen.getByRole('button', { name: 'История' }));
        await ui.click(screen.getByText('Все серверы'));
        await ui.click(screen.getByText('Majestic #14 (неактивен)'));
        await ui.click(screen.getByRole('button', { name: 'Применить' }));

        await waitFor(() => {
            expect(
                fetchMock.mock.calls.some(([requestUrl]) => String(requestUrl).includes('/api/complaints/history?') && String(requestUrl).includes('server=14')),
            ).toBe(true);
        });

    });

    it('edits complaint in modal and saves nested punishments without child delete endpoint', async () => {
        const fetchMock = createFetchMock();
        const ui = userEvent.setup();

        render(<ComplaintsPage />);

        await waitFor(() => {
            expect(screen.getByText('Жалоба #c1')).toBeInTheDocument();
        });

        const draftRow = screen.getByText('Жалоба #c1').closest('tr');
        expect(draftRow).toBeTruthy();
        await ui.click(within(draftRow as HTMLElement).getByTitle('Редактировать'));

        await waitFor(() => {
            expect(screen.getByText('Редактирование жалобы')).toBeInTheDocument();
        });

        const deleteButtons = screen.getAllByTitle('Удалить наказание');
        await ui.click(deleteButtons[1]);
        await ui.click(screen.getByRole('button', { name: 'Сохранить как черновик' }));

        await waitFor(() => {
            const patchCall = fetchMock.mock.calls.find(
                ([requestUrl, requestInit]) =>
                    String(requestUrl).includes('/api/complaints/c1')
                    && (requestInit as RequestInit | undefined)?.method === 'PATCH',
            );
            expect(patchCall).toBeTruthy();
            const body = JSON.parse(String((patchCall?.[1] as RequestInit).body));
            expect(body.target_status).toBe('draft');
            expect(body.media).toBe('Ник');
            expect(body.punishments).toHaveLength(1);
            expect(body.punishments[0].static).toBe(138254);
        });

        expect(
            fetchMock.mock.calls.some(
                ([requestUrl, requestInit]) =>
                    String(requestUrl).includes('/punishments/')
                    && (requestInit as RequestInit | undefined)?.method === 'DELETE',
            ),
        ).toBe(false);
    });

    it('submits draft complaint via target-status patch and issues pending complaint', async () => {
        const fetchMock = createFetchMock();
        const ui = userEvent.setup();

        render(<ComplaintsPage />);

        await waitFor(() => {
            expect(screen.getByText('Жалоба #c1')).toBeInTheDocument();
        });

        const draftRow = screen.getByText('Жалоба #c1').closest('tr');
        expect(draftRow).toBeTruthy();
        await ui.click(within(draftRow as HTMLElement).getByRole('button', { name: 'Отправить к выдаче' }));

        await waitFor(() => {
            const patchCall = fetchMock.mock.calls.find(
                ([requestUrl, requestInit]) =>
                    String(requestUrl).includes('/api/complaints/c1')
                    && (requestInit as RequestInit | undefined)?.method === 'PATCH',
            );
            expect(patchCall).toBeTruthy();
            const body = JSON.parse(String((patchCall?.[1] as RequestInit).body));
            expect(body).toEqual({ target_status: 'pending' });
        });

        const pendingRow = screen.getByText('Жалоба #c2').closest('tr');
        expect(pendingRow).toBeTruthy();
        await ui.click(within(pendingRow as HTMLElement).getByRole('button', { name: 'Выдать' }));

        await waitFor(() => {
            expect(
                fetchMock.mock.calls.some(
                    ([requestUrl, requestInit]) =>
                        String(requestUrl).includes('/api/complaints/c2/issue')
                        && (requestInit as RequestInit | undefined)?.method === 'POST',
                ),
            ).toBe(true);
        });
    });

    it('deletes whole complaint when removing the last punishment in editor', async () => {
        const fetchMock = createFetchMock();
        const ui = userEvent.setup();

        render(<ComplaintsPage />);

        await waitFor(() => {
            expect(screen.getByText('Жалоба #c3')).toBeInTheDocument();
        });

        const singleRow = screen.getByText('Жалоба #c3').closest('tr');
        expect(singleRow).toBeTruthy();
        await ui.click(within(singleRow as HTMLElement).getByTitle('Редактировать'));

        await waitFor(() => {
            expect(screen.getByText('Редактирование жалобы')).toBeInTheDocument();
        });

        await ui.click(screen.getByTitle('Удалить наказание'));
        await ui.click(screen.getAllByRole('button', { name: 'Удалить' }).at(-1) as HTMLElement);

        await waitFor(() => {
            expect(
                fetchMock.mock.calls.some(
                    ([requestUrl, requestInit]) =>
                        String(requestUrl).includes('/api/complaints/c3')
                        && (requestInit as RequestInit | undefined)?.method === 'DELETE',
                ),
            ).toBe(true);
        });
    });

    it('hides history admin controls when backend does not allow editing', async () => {
        createFetchMock();
        const ui = userEvent.setup();

        render(<ComplaintsPage />);

        await ui.click(screen.getByRole('button', { name: 'История' }));

        await waitFor(() => {
            expect(screen.getByText('Жалоба #c4')).toBeInTheDocument();
        });

        expect(screen.queryByTitle('Редактировать')).not.toBeInTheDocument();
        expect(screen.queryByTitle('Удалить жалобу')).not.toBeInTheDocument();
    });
});
