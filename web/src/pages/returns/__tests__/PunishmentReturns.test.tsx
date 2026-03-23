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

import PunishmentReturns from '../PunishmentReturns';

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

const createFetchMock = () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);

        if (url.includes('/api/game-servers')) {
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: gameServers,
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } },
            );
        }

        if (url.includes('/api/returns/queue')) {
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: [
                        {
                            id: '1',
                            punishment_type: 'mute',
                            static: 27253,
                            server: 14,
                            duration: 60,
                            remove_reason: 'На видео',
                            discord_message_url: 'https://discord.com/channels/test/message',
                            removed_by_id: '1001',
                            removed_by_name: 'akudama',
                            removed_at: '2026-03-07T10:00:00',
                            status: 'pending',
                            status_label: 'Готово',
                            remove_command: '/unmute 27253 На видео by akudama',
                            return_command: '/mute 27253 120 Возврат наказания by akudama',
                            can_claim: true,
                            can_complete: false,
                            can_release: false,
                            can_edit: true,
                            can_delete: true,
                        },
                        {
                            id: '3',
                            punishment_type: 'jail',
                            static: 138254,
                            server: 7,
                            duration: 13,
                            remove_reason: 'На стрим',
                            discord_message_url: null,
                            removed_by_id: '1002',
                            removed_by_name: 'gamzol',
                            removed_at: '2026-03-07T08:00:00',
                            claimed_by_id: '2002',
                            claimed_by_name: 'rodnoy',
                            claimed_at: '2026-03-07T20:00:00',
                            status: 'claimed',
                            status_label: 'В работе: rodnoy',
                            remove_command: '/unjail 138254 На стрим by gamzol',
                            return_command: '/ajail 138254 26 Возврат наказания by rodnoy',
                            can_claim: false,
                            can_complete: false,
                            can_release: false,
                            can_edit: false,
                            can_delete: false,
                        },
                        {
                            id: '4',
                            punishment_type: 'mute',
                            static: 50001,
                            server: 3,
                            duration: 45,
                            remove_reason: 'На видео',
                            discord_message_url: null,
                            removed_by_id: '1003',
                            removed_by_name: 'rodnoy',
                            removed_at: '2026-03-07T07:00:00',
                            claimed_by_id: '1001',
                            claimed_by_name: 'Tester',
                            claimed_at: '2026-03-07T20:10:00',
                            status: 'claimed',
                            status_label: 'В работе: Tester',
                            remove_command: '/unmute 50001 На видео by rodnoy',
                            return_command: '/mute 50001 90 Возврат наказания by Tester',
                            can_claim: false,
                            can_complete: true,
                            can_release: true,
                            can_edit: false,
                            can_delete: false,
                        },
                    ],
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } },
            );
        }

        if (url.includes('/api/returns/history')) {
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: {
                        items: [],
                        total: 0,
                        page: 1,
                        pages: 1,
                    },
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } },
            );
        }

        if (url.includes('/api/returns') && init?.method === 'POST') {
            const rawBody = typeof init.body === 'string' ? JSON.parse(init.body) : {};
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: {
                        id: '2',
                        punishment_type: rawBody.punishment_type ?? 'jail',
                        static: rawBody.static ?? 138254,
                        server: rawBody.server ?? 1,
                        duration: rawBody.duration ?? 13,
                        remove_reason: rawBody.remove_reason ?? 'На стрим',
                        discord_message_url: rawBody.discord_message_url ?? null,
                        removed_by_id: '1',
                        removed_by_name: 'Tester',
                        removed_at: '2026-03-07T12:00:00',
                        status: 'pending',
                        status_label: 'Ждет до 08.03 00:00',
                        remove_command: '/unjail 138254 На стрим by Tester',
                        return_command: '/ajail 138254 26 Возврат наказания by Tester',
                        can_claim: false,
                        can_complete: false,
                        can_release: false,
                        can_edit: true,
                        can_delete: true,
                    },
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } },
            );
        }

        if (url.includes('/api/returns/4/release') && init?.method === 'POST') {
            return new Response(
                JSON.stringify({
                    status: 'success',
                    data: {
                        id: '4',
                        punishment_type: 'mute',
                        static: 50001,
                        server: 3,
                        duration: 45,
                        remove_reason: 'На видео',
                        discord_message_url: null,
                        removed_by_id: '1003',
                        removed_by_name: 'rodnoy',
                        removed_at: '2026-03-07T07:00:00',
                        claimed_by_id: null,
                        claimed_by_name: null,
                        claimed_at: null,
                        status: 'pending',
                        status_label: 'Готово',
                        remove_command: '/unmute 50001 На видео by rodnoy',
                        return_command: '/mute 50001 90 Возврат наказания by Tester',
                        can_claim: true,
                        can_complete: false,
                        can_release: false,
                        can_edit: false,
                        can_delete: false,
                    },
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } },
            );
        }

        return new Response('{}', { status: 404 });
    });

    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
};

describe('PunishmentReturns', () => {
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
                'returns.queue.view': true,
                'returns.create': true,
                'returns.process': true,
                'returns.history.view': true,
                'returns.manage.self': true,
                'returns.manage.any': true,
            },
        };
    });

    it('opens assistant profile from claimed status badge', async () => {
        createFetchMock();
        const ui = userEvent.setup();

        render(<PunishmentReturns />);

        await waitFor(() => {
            expect(screen.getByRole('button', { name: 'rodnoy' })).toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: 'rodnoy' }));

        expect(navigateMock).toHaveBeenCalledWith('/assistants/2002');
    });

    it('renders queue and opens history filters', async () => {
        const fetchMock = createFetchMock();
        const ui = userEvent.setup();

        render(<PunishmentReturns />);

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalled();
            expect(screen.getByText('27253')).toBeInTheDocument();
            expect(screen.getByText('Majestic #14')).toBeInTheDocument();
            expect(screen.getByText('Готово')).toBeInTheDocument();
        });

        await ui.click(screen.getByText('История'));

        await waitFor(() => {
            expect(screen.getByText('Все серверы')).toBeInTheDocument();
            expect(screen.getByText('История пуста')).toBeInTheDocument();
        });
    });

    it('keeps inactive server visible in edit mode and filters history by server', async () => {
        const fetchMock = createFetchMock();
        const ui = userEvent.setup();

        render(<PunishmentReturns />);

        await waitFor(() => {
            expect(screen.getByText('Majestic #14')).toBeInTheDocument();
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
                fetchMock.mock.calls.some(([requestUrl]) => String(requestUrl).includes('/api/returns/history?') && String(requestUrl).includes('server=14')),
            ).toBe(true);
        });
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
                'returns.history.view': true,
            },
        };

        render(<PunishmentReturns />);

        await waitFor(() => {
            expect(screen.getByText('История пуста')).toBeInTheDocument();
        });

        expect(screen.queryByRole('button', { name: 'К возврату' })).not.toBeInTheDocument();
        expect(
            fetchMock.mock.calls.some(([requestUrl]) => String(requestUrl).includes('/api/returns/queue')),
        ).toBe(false);
        expect(
            fetchMock.mock.calls.some(([requestUrl]) => String(requestUrl).includes('/api/returns/history')),
        ).toBe(true);
    });

    it('shows release button for current claimer', async () => {
        createFetchMock();

        render(<PunishmentReturns />);

        await waitFor(() => {
            expect(screen.getByRole('button', { name: 'Отменить' })).toBeInTheDocument();
        });
    });

    it('releases claimed return back to queue', async () => {
        const fetchMock = createFetchMock();
        const ui = userEvent.setup();

        render(<PunishmentReturns />);

        await waitFor(() => {
            expect(screen.getByRole('button', { name: 'Отменить' })).toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: 'Отменить' }));

        await waitFor(() => {
            const releaseCall = fetchMock.mock.calls.find(
                ([requestUrl, requestInit]) =>
                    String(requestUrl).includes('/api/returns/4/release') &&
                    (requestInit as RequestInit | undefined)?.method === 'POST',
            );

            expect(releaseCall).toBeTruthy();
        });
    });

    it('shows copy button and hides return command preview in create modal', async () => {
        createFetchMock();
        const ui = userEvent.setup();

        render(<PunishmentReturns />);

        await waitFor(() => {
            expect(screen.getByText('27253')).toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: 'Снять с возвратом' }));

        expect(screen.getByText('Команда снятия')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Скопировать' })).toBeInTheDocument();
        expect(screen.queryByText('Команда возврата')).not.toBeInTheDocument();
    });

    it('submits create form without discord link', async () => {
        const fetchMock = createFetchMock();
        const ui = userEvent.setup();

        render(<PunishmentReturns />);

        await waitFor(() => {
            expect(screen.getByText('27253')).toBeInTheDocument();
        });

        await ui.click(screen.getByRole('button', { name: 'Снять с возвратом' }));

        const staticInput = screen.getByPlaceholderText('Например, 138254');
        const durationInput = screen.getByPlaceholderText('Например, 30');

        await ui.clear(staticInput);
        await ui.type(staticInput, '138254');
        await ui.clear(durationInput);
        await ui.type(durationInput, '13');
        await ui.click(screen.getByRole('button', { name: 'Создать возврат' }));

        await waitFor(() => {
            const postCall = fetchMock.mock.calls.find(
                ([requestUrl, requestInit]) =>
                    String(requestUrl).includes('/api/returns') &&
                    (requestInit as RequestInit | undefined)?.method === 'POST',
            );

            expect(postCall).toBeTruthy();

            const requestInit = postCall?.[1] as RequestInit;
            expect(JSON.parse(String(requestInit.body))).toMatchObject({
                static: 138254,
                server: 1,
                duration: 13,
                discord_message_url: null,
            });
        });
    });
});
