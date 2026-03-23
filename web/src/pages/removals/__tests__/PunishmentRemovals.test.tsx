import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
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

import PunishmentRemovals from '../PunishmentRemovals';

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

async function selectRemovalReason(ui: ReturnType<typeof userEvent.setup>, value: 'На видео' | 'На стрим') {
    const reasonField = screen.getAllByText('Причина')[0].parentElement as HTMLElement;
    const trigger = within(reasonField).getByText(/На видео|На стрим/);
    await ui.click(trigger);
    await ui.click(screen.getAllByText(value).at(-1) as HTMLElement);
}

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

        if (url.includes('/api/removals/queue')) {
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: [
                        {
                            id: 'r1',
                            assistant_id: '1001',
                            assistant_name: 'Tester',
                            created_by_id: '1001',
                            created_by_name: 'Tester',
                            reviewed_by_id: null,
                            reviewed_by_name: null,
                            issued_by_id: null,
                            issued_by_name: null,
                            status: 'draft',
                            status_label: 'Черновик',
                            punishment_type: 'unjail',
                            static: 27253,
                            server: 14,
                            reason: 'На видео',
                            message_link: 'https://discord.com/channels/test/removal',
                            command: '/unjail 27253 На видео by Tester',
                            created_at: '2026-03-20T09:00:00',
                            reviewed_at: null,
                            issued_at: null,
                            can_edit: true,
                            can_delete: true,
                            can_submit: true,
                            can_issue: false,
                        },
                        {
                            id: 'r2',
                            assistant_id: '1001',
                            assistant_name: 'Tester',
                            created_by_id: '1001',
                            created_by_name: 'Tester',
                            reviewed_by_id: '2002',
                            reviewed_by_name: 'Admin',
                            issued_by_id: null,
                            issued_by_name: null,
                            status: 'pending',
                            status_label: 'К выдаче',
                            punishment_type: 'unmute',
                            static: 50001,
                            server: 3,
                            reason: 'На стрим',
                            message_link: null,
                            command: '/unmute 50001 На стрим by Tester',
                            created_at: '2026-03-20T10:00:00',
                            reviewed_at: '2026-03-20T10:15:00',
                            issued_at: null,
                            can_edit: true,
                            can_delete: true,
                            can_submit: false,
                            can_issue: true,
                        },
                    ],
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } },
            );
        }

        if (url.includes('/api/removals/r1') && method === 'GET') {
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: {
                        id: 'r1',
                        assistant_id: '1001',
                        assistant_name: 'Tester',
                        created_by_id: '1001',
                        created_by_name: 'Tester',
                        reviewed_by_id: null,
                        reviewed_by_name: null,
                        issued_by_id: null,
                        issued_by_name: null,
                        status: 'draft',
                        status_label: 'Черновик',
                        punishment_type: 'unjail',
                        static: 27253,
                        server: 14,
                        reason: 'На видео',
                        message_link: 'https://discord.com/channels/test/removal',
                        command: '/unjail 27253 На видео by Tester',
                        created_at: '2026-03-20T09:00:00',
                        reviewed_at: null,
                        issued_at: null,
                        can_edit: true,
                        can_delete: true,
                        can_submit: true,
                        can_issue: false,
                    },
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } },
            );
        }

        if (url.includes('/api/removals/history')) {
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: {
                        items: [
                            {
                                id: 'r3',
                                assistant_id: '1001',
                                assistant_name: 'Tester',
                                created_by_id: '1001',
                                created_by_name: 'Tester',
                                reviewed_by_id: '2002',
                                reviewed_by_name: 'Admin',
                                issued_by_id: '2002',
                                issued_by_name: 'Admin',
                                status: 'issued',
                                status_label: 'Выдано',
                                punishment_type: 'unjail',
                                static: 44444,
                                server: 5,
                                reason: 'На видео',
                                message_link: 'https://discord.com/channels/test/history',
                                command: '/unjail 44444 На видео by Admin',
                                created_at: '2026-03-19T08:10:00',
                                reviewed_at: '2026-03-19T09:00:00',
                                issued_at: '2026-03-19T10:00:00',
                                can_edit: false,
                                can_delete: false,
                                can_submit: false,
                                can_issue: false,
                            },
                        ],
                        total: 1,
                        page: 1,
                        pages: 1,
                    },
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } },
            );
        }

        if (url.includes('/api/removals') && method === 'POST') {
            return new Response(JSON.stringify({ status: 'success', data: { id: 'r99' } }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        if (url.includes('/api/removals/r1') && method === 'PATCH') {
            return new Response(JSON.stringify({ status: 'success', data: {} }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        if (url.includes('/api/removals/r2/issue') && method === 'POST') {
            return new Response(JSON.stringify({ status: 'success', data: {} }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        if (url.includes('/api/removals/r3') && method === 'DELETE') {
            return new Response(JSON.stringify({ status: 'success', data: {} }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        }

        return new Response('{}', { status: 404 });
    });

    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
};

describe('PunishmentRemovals', () => {
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
                'removals.queue.view': true,
                'removals.create': true,
                'removals.issue': true,
                'removals.history.view': true,
                'removals.manage.self': true,
                'removals.manage.any': true,
            },
        };
    });

    it('renders queue/history and supports draft and pending actions', async () => {
        createFetchMock();
        const ui = userEvent.setup();

        render(<PunishmentRemovals />);

        await waitFor(() => {
            expect(screen.getByText('Черновик')).toBeInTheDocument();
            expect(screen.getByRole('button', { name: 'К выдаче' })).toBeInTheDocument();
            expect(screen.getByText('Majestic #14')).toBeInTheDocument();
        });

        expect(screen.getByRole('button', { name: 'Отправить к выдаче' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Выдать' })).toBeInTheDocument();

        await ui.click(screen.getByRole('button', { name: 'История' }));

        await waitFor(() => {
            expect(screen.getByText('Выдано')).toBeInTheDocument();
        });
    });

    it('filters removal history by server and keeps inactive server visible in edit mode', async () => {
        const fetchMock = createFetchMock();
        const ui = userEvent.setup();

        render(<PunishmentRemovals />);

        await waitFor(() => {
            expect(screen.getByText('27253')).toBeInTheDocument();
        });

        const queueRow = screen.getByText('27253').closest('tr');
        expect(queueRow).toBeTruthy();
        await ui.click(within(queueRow as HTMLElement).getByTitle('Редактировать'));

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
                fetchMock.mock.calls.some(([requestUrl]) => String(requestUrl).includes('/api/removals/history?') && String(requestUrl).includes('server=14')),
            ).toBe(true);
        });

    });

    it('opens history by default for history-only users and skips queue request', async () => {
        const fetchMock = createFetchMock();
        const ui = userEvent.setup();
        mockedUser = {
            id: '2',
            discord_id: '2001',
            username: 'auditor',
            nickname: 'Auditor',
            role: 'employee',
            require_password_change: false,
            permissions: {
                'removals.history.view': true,
            },
        };

        render(<PunishmentRemovals />);

        await waitFor(() => {
            expect(screen.getByText('Выдано')).toBeInTheDocument();
        });

        expect(screen.queryByRole('button', { name: 'К выдаче' })).not.toBeInTheDocument();
        expect(fetchMock.mock.calls.some(([requestUrl]) => String(requestUrl).includes('/api/removals/queue'))).toBe(false);
        expect(fetchMock.mock.calls.some(([requestUrl]) => String(requestUrl).includes('/api/removals/history'))).toBe(true);

        await ui.click(screen.getByRole('button', { name: 'История' }));
    });

    it('creates removal in draft state and edits existing removal to pending', async () => {
        const fetchMock = createFetchMock();
        const ui = userEvent.setup();

        render(<PunishmentRemovals />);

        await waitFor(() => {
            expect(screen.getByText('Создать снятие')).toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: 'Создать снятие' }));

        await ui.type(screen.getByPlaceholderText('Например, 138254'), '138254');
        await selectRemovalReason(ui, 'На стрим');
        await ui.type(screen.getByPlaceholderText('https://discord.com/channels/...'), 'https://discord.com/channels/test/new');

        await ui.click(screen.getByRole('button', { name: 'Сохранить как черновик' }));

        await waitFor(() => {
            const postCall = fetchMock.mock.calls.find(
                ([requestUrl, requestInit]) =>
                    String(requestUrl).includes('/api/removals') &&
                    !String(requestUrl).includes('/api/removals/r1') &&
                    (requestInit as RequestInit | undefined)?.method === 'POST',
            );

            expect(postCall).toBeTruthy();
            const body = JSON.parse(String((postCall?.[1] as RequestInit).body));
            expect(body).toMatchObject({
                punishment_type: 'unjail',
                static: 138254,
                server: 1,
                reason: 'На стрим',
                message_link: 'https://discord.com/channels/test/new',
                target_status: 'draft',
            });
        });

        const row = screen.getByText('27253').closest('tr');
        expect(row).toBeTruthy();
        await ui.click(within(row as HTMLElement).getByRole('button', { name: 'Редактировать' }));
        await selectRemovalReason(ui, 'На стрим');
        await ui.click(screen.getByRole('button', { name: 'Сохранить как черновик' }));

        await waitFor(() => {
            const patchCall = fetchMock.mock.calls.find(
                ([requestUrl, requestInit]) =>
                    String(requestUrl).includes('/api/removals/r1') &&
                    (requestInit as RequestInit | undefined)?.method === 'PATCH',
            );

            expect(patchCall).toBeTruthy();
            const body = JSON.parse(String((patchCall?.[1] as RequestInit).body));
            expect(body.target_status).toBe('draft');
            expect(body.reason).toBe('На стрим');
        });
    });

    it('submits draft row to pending and issues pending row', async () => {
        const fetchMock = createFetchMock();
        const ui = userEvent.setup();

        render(<PunishmentRemovals />);

        await waitFor(() => {
            expect(screen.getByText('27253')).toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: 'Отправить к выдаче' }));

        await waitFor(() => {
            const patchCall = fetchMock.mock.calls.find(
                ([requestUrl, requestInit]) =>
                    String(requestUrl).includes('/api/removals/r1') &&
                    (requestInit as RequestInit | undefined)?.method === 'PATCH',
            );

            expect(patchCall).toBeTruthy();
            const body = JSON.parse(String((patchCall?.[1] as RequestInit).body));
            expect(body.target_status).toBe('pending');
            expect(body.server).toBe(14);
        });

        await ui.click(screen.getByRole('button', { name: 'Выдать' }));

        await waitFor(() => {
            const issueCall = fetchMock.mock.calls.find(
                ([requestUrl, requestInit]) =>
                    String(requestUrl).includes('/api/removals/r2/issue') &&
                    (requestInit as RequestInit | undefined)?.method === 'POST',
            );

            expect(issueCall).toBeTruthy();
        });
    });

    it('hides history admin controls when backend does not allow editing', async () => {
        createFetchMock();
        const ui = userEvent.setup();

        render(<PunishmentRemovals />);

        await ui.click(screen.getByRole('button', { name: 'История' }));

        await waitFor(() => {
            expect(screen.getByText('Выдано')).toBeInTheDocument();
        });

        expect(screen.queryByTitle('Редактировать')).not.toBeInTheDocument();
        expect(screen.queryByTitle('Удалить')).not.toBeInTheDocument();
    });
});
