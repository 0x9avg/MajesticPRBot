import type { PunishmentRemovalReason, PunishmentRemovalType } from '../../types/domain';

export const REMOVAL_PUNISHMENT_OPTIONS = [
    { value: 'unjail', label: 'Unjail' },
    { value: 'unmute', label: 'Unmute' },
] as const;

export const REMOVAL_REASON_OPTIONS = [
    { value: 'На видео', label: 'На видео' },
    { value: 'На стрим', label: 'На стрим' },
] as const;

export const REMOVAL_STATUS_LABELS: Record<string, string> = {
    draft: 'Черновик',
    pending: 'К выдаче',
    issued: 'Выдано',
    completed: 'Выдано',
};

export function formatRemovalTypeLabel(value: PunishmentRemovalType): string {
    return value === 'unjail' ? 'Unjail' : 'Unmute';
}

export function formatRemovalStatusLabel(status: string | null | undefined): string {
    if (!status) return 'Черновик';
    return REMOVAL_STATUS_LABELS[status] || status;
}

export function normalizeRemovalReason(value: string | null | undefined): PunishmentRemovalReason {
    return value === 'На стрим' ? 'На стрим' : 'На видео';
}

export function buildRemovalCommand(
    removalType: PunishmentRemovalType,
    staticValue: string | number,
    reason: string,
    actorName: string,
): string {
    const command = removalType === 'unjail' ? '/unjail' : '/unmute';
    const resolvedStatic = String(staticValue || '0');
    const resolvedReason = reason.trim();
    return `${command} ${resolvedStatic} ${resolvedReason} by ${actorName}`.trim();
}
