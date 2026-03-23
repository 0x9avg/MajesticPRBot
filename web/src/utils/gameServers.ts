import type { GameServerDto } from '../types/domain';

export type GameServerLabelVariant = 'full' | 'short' | 'command';

export type GameServerOption = {
    value: string;
    label: string;
};

export interface BuildGameServerOptionsParams {
    variant?: GameServerLabelVariant;
    includeInactive?: boolean;
    includeEmptyOptionLabel?: string;
    selectedServerId?: string | number | null;
}

function normalizeServerId(server: string | number | null | undefined): number | null {
    if (server === null || server === undefined || server === '') return null;
    const parsed = Number(server);
    return Number.isFinite(parsed) ? parsed : null;
}

function fallbackLabel(id: number, variant: GameServerLabelVariant): string {
    if (variant === 'short') return `#${id}`;
    if (variant === 'command') return `RU${id}`;
    return `Majestic #${id}`;
}

function getLabelFromServer(server: GameServerDto, variant: GameServerLabelVariant): string {
    if (variant === 'short') return server.short_name;
    if (variant === 'command') return server.command_name;
    return server.full_name;
}

export function formatGameServerLabel(
    server: GameServerDto | number | string | null | undefined,
    variant: GameServerLabelVariant = 'full',
    serversById?: Record<number, GameServerDto>,
): string {
    if (server === null || server === undefined || server === '') {
        return 'Не задан';
    }

    if (typeof server === 'object') {
        return getLabelFromServer(server, variant);
    }

    const serverId = normalizeServerId(server);
    if (serverId === null) return 'Не задан';

    const resolved = serversById?.[serverId];
    if (resolved) {
        return getLabelFromServer(resolved, variant);
    }

    return fallbackLabel(serverId, variant);
}

export function buildGameServerOptions(
    servers: GameServerDto[],
    params: BuildGameServerOptionsParams = {},
): GameServerOption[] {
    const {
        variant = 'full',
        includeInactive = false,
        includeEmptyOptionLabel,
        selectedServerId,
    } = params;

    const selectedId = normalizeServerId(selectedServerId);
    const filtered = servers.filter((server) => (
        server.is_active || includeInactive || server.id === selectedId
    ));

    const options = filtered
        .slice()
        .sort((left, right) => (left.sort_order - right.sort_order) || (left.id - right.id))
        .map((server) => ({
            value: String(server.id),
            label: `${getLabelFromServer(server, variant)}${server.is_active ? '' : ' (неактивен)'}`,
        }));

    if (includeEmptyOptionLabel) {
        return [{ value: '', label: includeEmptyOptionLabel }, ...options];
    }

    return options;
}

export function getDefaultActiveGameServerId(servers: GameServerDto[]): string {
    const activeServer = servers
        .slice()
        .sort((left, right) => (left.sort_order - right.sort_order) || (left.id - right.id))
        .find((server) => server.is_active);

    return String(activeServer?.id ?? servers[0]?.id ?? '');
}
