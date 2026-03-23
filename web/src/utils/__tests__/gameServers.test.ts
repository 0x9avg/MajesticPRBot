import { describe, expect, it } from 'vitest';
import {
    buildGameServerOptions,
    formatGameServerLabel,
    getDefaultActiveGameServerId,
} from '../gameServers';

const servers = [
    {
        id: 2,
        full_name: 'Majestic #2',
        short_name: '#2',
        command_name: 'RU2',
        sort_order: 2,
        is_active: false,
    },
    {
        id: 1,
        full_name: 'Majestic #1',
        short_name: '#1',
        command_name: 'RU1',
        sort_order: 1,
        is_active: true,
    },
] as const;

describe('gameServers utils', () => {
    it('formats labels from catalog and fallback ids', () => {
        const byId = Object.fromEntries(servers.map((server) => [server.id, server])) as Record<number, typeof servers[number]>;

        expect(formatGameServerLabel(servers[0], 'full')).toBe('Majestic #2');
        expect(formatGameServerLabel(1, 'short', byId)).toBe('#1');
        expect(formatGameServerLabel(2, 'command', byId)).toBe('RU2');
        expect(formatGameServerLabel(17, 'full')).toBe('Majestic #17');
        expect(formatGameServerLabel(null, 'full')).toBe('Не задан');
    });

    it('builds select options with inactive suffix and empty option label', () => {
        const activeOnly = buildGameServerOptions(servers as unknown as typeof servers[number][], {
            includeInactive: false,
            selectedServerId: 2,
        });
        expect(activeOnly).toEqual([{ value: '1', label: 'Majestic #1' }, { value: '2', label: 'Majestic #2 (неактивен)' }]);

        const withEmpty = buildGameServerOptions(servers as unknown as typeof servers[number][], {
            includeInactive: true,
            includeEmptyOptionLabel: 'Все серверы',
            variant: 'command',
        });
        expect(withEmpty[0]).toEqual({ value: '', label: 'Все серверы' });
        expect(withEmpty[1]).toEqual({ value: '1', label: 'RU1' });
        expect(withEmpty[2]).toEqual({ value: '2', label: 'RU2 (неактивен)' });
    });

    it('returns the first active server id as default', () => {
        expect(getDefaultActiveGameServerId(servers as unknown as typeof servers[number][])).toBe('1');
    });
});
