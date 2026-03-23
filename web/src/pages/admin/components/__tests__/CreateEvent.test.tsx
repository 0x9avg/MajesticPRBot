import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../../utils/datetime', async () => {
    const actual = await vi.importActual<typeof import('../../../../utils/datetime')>('../../../../utils/datetime');
    return {
        ...actual,
        getMskTodayStr: () => '2026-03-21',
        formatToMskIso: () => '2026-03-21T20:07:00',
    };
});

import CreateEvent from '../CreateEvent';

describe('CreateEvent', () => {
    beforeEach(() => {
        vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-03-21T17:07:00.000Z').getTime());
    });

    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('renders current Moscow date and time by default', () => {
        render(<CreateEvent />);

        expect(screen.getByText('21.03.2026')).toBeInTheDocument();
        expect(screen.getByText('20:07')).toBeInTheDocument();
    });

    it('submits the default Moscow start time without false past-date validation', async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    status: 'success',
                    data: { id: 55 },
                }),
                {
                    status: 201,
                    headers: { 'Content-Type': 'application/json' },
                }
            )
        );
        vi.stubGlobal('fetch', fetchMock);

        render(<CreateEvent />);

        fireEvent.change(screen.getByPlaceholderText('Например: Собрание'), {
            target: { value: 'Собрание' },
        });
        fireEvent.change(screen.getByPlaceholderText('Краткое описание события...'), {
            target: { value: 'Плановое собрание' },
        });
        fireEvent.click(screen.getByRole('button', { name: 'Создать событие' }));

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalled();
        });

        const [, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
        const body = JSON.parse(String(init.body));

        expect(body.start_time).toBe('2026-03-21T20:07:00');
        expect(screen.queryByText('Дата и время начала не могут быть в прошлом')).not.toBeInTheDocument();
    });
});
