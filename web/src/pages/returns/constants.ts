export const RETURN_SERVER_OPTIONS = Array.from({ length: 17 }, (_, index) => ({
    value: String(index + 1),
    label: `Majestic #${index + 1}`,
}));

export const RETURN_REASON_OPTIONS = [
    { value: 'На стрим', label: 'На стрим' },
    { value: 'На видео', label: 'На видео' },
] as const;

export const RETURN_PUNISHMENT_OPTIONS = [
    { value: 'jail', label: 'Jail / Unjail' },
    { value: 'mute', label: 'Mute / Unmute' },
] as const;

export function formatReturnServerLabel(server: number | string | null | undefined): string {
    const parsed = Number(server);
    if (!Number.isFinite(parsed) || parsed < 1) return 'Majestic';
    return `Majestic #${parsed}`;
}

export function formatPunishmentLabel(value: 'jail' | 'mute'): string {
    return value === 'jail' ? 'Jail' : 'Mute';
}

export function formatCommandPairLabel(value: 'jail' | 'mute'): string {
    return value === 'jail' ? 'unjail -> ajail' : 'unmute -> mute';
}
