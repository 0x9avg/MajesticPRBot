import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi, describe, it, beforeEach, afterEach, expect } from 'vitest';
import UserRegistration from '../UserRegistration';
import type { UserContext } from '../../../../types/auth';
import { setAccessToken } from '../../../../api/client';

let mockedUser: UserContext | null = null;

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

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
    return {
        ...actual,
        useOutletContext: () => ({ user: mockedUser }),
    };
});

const makeUser = (
    role: UserContext['role'],
    canRegisterUsers: boolean
): UserContext => ({
    id: 1,
    discord_id: '1001',
    username: 'tester',
    nickname: 'Tester',
    role,
    require_password_change: false,
    permissions: {
        'admin.users.create': canRegisterUsers,
    },
});

describe('UserRegistration', () => {
    beforeEach(() => {
        mockedUser = makeUser('manager', true);
        vi.stubGlobal('localStorage', createLocalStorageMock());
        localStorage.clear();
        setAccessToken(null);
    });

    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('shows manager-allowed roles only (no manager/developer)', async () => {
        const ui = userEvent.setup();
        render(<UserRegistration />);

        await ui.click(screen.getByText('Выберите роль'));

        expect(screen.getByText('Младший ассистент')).toBeInTheDocument();
        expect(screen.getByText('Ассистент')).toBeInTheDocument();
        expect(screen.getByText('Старший ассистент')).toBeInTheDocument();
        expect(screen.queryByText('Глава ассистентов')).not.toBeInTheDocument();
        expect(screen.queryByText('Разработчик')).not.toBeInTheDocument();
    });

    it('includes developer role for developer user', async () => {
        mockedUser = makeUser('developer', true);
        const ui = userEvent.setup();
        render(<UserRegistration />);

        await ui.click(screen.getByText('Выберите роль'));

        expect(screen.getByText('Разработчик')).toBeInTheDocument();
    });

    it('disables form when user has no admin.users.create permission', () => {
        mockedUser = makeUser('manager', false);
        render(<UserRegistration />);

        expect(screen.getByText('Недостаточно прав для регистрации пользователей')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Создать пользователя' })).toBeDisabled();
    });

    it('renders API 403 error message from backend', async () => {
        mockedUser = makeUser('manager', true);
        setAccessToken('test-token');

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({ detail: 'Нельзя создавать пользователя с ролью выше вашей' }),
                {
                    status: 403,
                    headers: { 'Content-Type': 'application/json' },
                }
            )
        );
        vi.stubGlobal('fetch', fetchMock);

        const ui = userEvent.setup();
        render(<UserRegistration />);

        await ui.type(screen.getByPlaceholderText('user_login'), 'new_user');
        await ui.type(screen.getAllByRole('textbox')[1], 'New User');
        await ui.type(screen.getByPlaceholderText('000000000000000000'), '123456789');
        await ui.click(screen.getByText('Выберите роль'));
        await ui.click(screen.getByText('Ассистент'));
        await ui.click(screen.getByRole('button', { name: 'Создать пользователя' }));

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalled();
            expect(screen.getByText('Нельзя создавать пользователя с ролью выше вашей')).toBeInTheDocument();
        });

        expect(fetchMock.mock.calls.some(([requestUrl]) => String(requestUrl).includes('/api/admin/users'))).toBe(true);
    });
});
