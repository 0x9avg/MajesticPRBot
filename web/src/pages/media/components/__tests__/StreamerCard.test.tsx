import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { UserContext } from '../../../../types/auth';
import type { Streamer } from '../../../../types/domain';
import StreamerCard from '../StreamerCard';

let mockedUser: UserContext | null = null;
const navigateMock = vi.fn();

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
    return {
        ...actual,
        useNavigate: () => navigateMock,
        useOutletContext: () => ({ user: mockedUser }),
    };
});

const streamer: Streamer = {
    streamer_id: 'streamer-1',
    streamer_name: 'Alpha',
    priority: 2,
    pr_slots: 2,
};

const makeUser = (permissions: Record<string, boolean>): UserContext => ({
    id: '1',
    discord_id: '1001',
    username: 'tester',
    nickname: 'Tester',
    role: 'employee',
    require_password_change: false,
    permissions,
});

describe('StreamerCard', () => {
    it('shows only settings button for update-only access', () => {
        mockedUser = makeUser({
            'media.view': true,
            'media.update': true,
            'media.delete': false,
        });

        render(
            <StreamerCard
                streamer={streamer}
                onSettingsClick={vi.fn()}
                onDelete={vi.fn()}
            />,
        );

        expect(screen.getByTitle('Настройки стримера')).toBeInTheDocument();
        expect(screen.queryByTitle('Удалить стримера')).not.toBeInTheDocument();
    });

    it('shows only delete button for delete-only access', () => {
        mockedUser = makeUser({
            'media.view': true,
            'media.update': false,
            'media.delete': true,
        });

        render(
            <StreamerCard
                streamer={streamer}
                onSettingsClick={vi.fn()}
                onDelete={vi.fn()}
            />,
        );

        expect(screen.queryByTitle('Настройки стримера')).not.toBeInTheDocument();
        expect(screen.getByTitle('Удалить стримера')).toBeInTheDocument();
    });
});
