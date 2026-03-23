import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { setAccessToken } from '../../api/client';
import UserProfile from '../UserProfile';

const navigateMock = vi.fn();

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
    return {
        ...actual,
        useNavigate: () => navigateMock,
        useParams: () => ({ id: '1001' }),
    };
});

describe('UserProfile', () => {
    beforeEach(() => {
        navigateMock.mockReset();
        setAccessToken('test-token');
    });

    afterEach(() => {
        setAccessToken(null);
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('shows explicit access denied message on assistant profile 403', async () => {
        const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
            const url = String(input);

            if (url === '/api/assistants/1001') {
                return new Response(JSON.stringify({ detail: 'forbidden' }), {
                    status: 403,
                    headers: { 'Content-Type': 'application/json' },
                });
            }

            return new Response('{}', { status: 404 });
        });
        vi.stubGlobal('fetch', fetchMock);

        render(<UserProfile />);

        await waitFor(() => {
            expect(screen.getByText('Недостаточно прав для просмотра PR-профиля.')).toBeInTheDocument();
        });
    });

    it('renders warning display from canonical strict/oral fields', async () => {
        const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
            const url = String(input);

            if (url === '/api/assistants/1001') {
                return new Response(JSON.stringify({
                    status: 'success',
                    data: {
                        pr_id: '1001',
                        nickname: 'Tester',
                        role: 'employee',
                        experience_days: 12,
                        status: 'free',
                        total_spec_seconds: 7200,
                        total_spec_hours: 2,
                        gross_points: 12.5,
                        net_points: 10.5,
                        active_point_penalty: 2,
                        active_percent_penalty: 0,
                        active_checks: 0,
                        active_strict_warnings: 1,
                        active_oral_warnings: 0,
                    },
                }), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                });
            }

            if (url === '/api/assistants/1001/logs') {
                return new Response(JSON.stringify({ status: 'success', data: [] }), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                });
            }

            return new Response('{}', { status: 404 });
        });
        vi.stubGlobal('fetch', fetchMock);

        render(<UserProfile />);

        await waitFor(() => {
            expect(screen.getByText('Tester')).toBeInTheDocument();
        });

        expect(screen.getByText('1/2 0/2')).toBeInTheDocument();
    });
});
