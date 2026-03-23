export const RETURN_REASON_OPTIONS = [
    { value: 'На стрим', label: 'На стрим' },
    { value: 'На видео', label: 'На видео' },
] as const;

export const RETURN_PUNISHMENT_OPTIONS = [
    { value: 'jail', label: 'Jail / Unjail' },
    { value: 'mute', label: 'Mute / Unmute' },
] as const;

export type ReturnPunishmentType = typeof RETURN_PUNISHMENT_OPTIONS[number]['value'];
export type ReturnRemoveReason = typeof RETURN_REASON_OPTIONS[number]['value'];

export function formatPunishmentLabel(value: 'jail' | 'mute'): string {
    return value === 'jail' ? 'Jail' : 'Mute';
}

export function formatCommandPairLabel(value: 'jail' | 'mute'): string {
    return value === 'jail' ? 'unjail -> ajail' : 'unmute -> mute';
}

export function buildRemoveCommand(
    punishmentType: ReturnPunishmentType,
    staticValue: string | number,
    removeReason: ReturnRemoveReason,
    actorName: string,
): string {
    const command = punishmentType === 'jail' ? '/unjail' : '/unmute';
    const resolvedStatic = String(staticValue || '0');
    return `${command} ${resolvedStatic} ${removeReason} by ${actorName}`;
}

export function buildReturnCommand(
    punishmentType: ReturnPunishmentType,
    staticValue: string | number,
    durationValue: string | number,
    actorName: string,
): string {
    const command = punishmentType === 'jail' ? '/ajail' : '/mute';
    const resolvedStatic = String(staticValue || '0');
    const resolvedDuration = Number(durationValue || 0) * 2;
    return `${command} ${resolvedStatic} ${resolvedDuration} Возврат наказания by ${actorName}`;
}
