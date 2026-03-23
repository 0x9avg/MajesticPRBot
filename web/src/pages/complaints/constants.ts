import type { ComplaintPunishmentType } from '../../types/domain';

type ComplaintPunishmentLike = {
    punishment_type: ComplaintPunishmentType;
    static: string | number;
    duration?: string | number | null;
    reason: string;
};

type ComplaintPreviewContext = {
    media?: string | null;
    incident_at?: string | null;
};

export const COMPLAINT_PUNISHMENT_OPTIONS = [
    { value: 'mute', label: 'Mute' },
    { value: 'ajail', label: 'Ajail' },
    { value: 'warn', label: 'Warn' },
    { value: 'ban', label: 'Ban' },
    { value: 'hardban', label: 'Hardban' },
    { value: 'gunban', label: 'Gunban' },
] as const;

export const COMPLAINT_STATUS_LABELS: Record<string, string> = {
    draft: 'Черновик',
    pending: 'К выдаче',
    issued: 'Выдано',
    completed: 'Выдано',
};

const COMPLAINT_COMMAND_RULES: Record<
    ComplaintPunishmentType,
    {
        command: string;
        label: string;
        durationUnit: string | null;
        durationTextUnit: string | null;
    }
> = {
    mute: { command: '/mute', label: 'Mute', durationUnit: 'мин', durationTextUnit: 'минут' },
    ajail: { command: '/ajail', label: 'Ajail', durationUnit: 'мин', durationTextUnit: 'минут' },
    warn: { command: '/warn', label: 'Warn', durationUnit: null, durationTextUnit: null },
    ban: { command: '/ban', label: 'Ban', durationUnit: 'дн', durationTextUnit: 'дней' },
    hardban: { command: '/hardban', label: 'HardBan', durationUnit: 'дн', durationTextUnit: 'дней' },
    gunban: { command: '/gunban', label: 'GunBan', durationUnit: 'ч', durationTextUnit: 'часов' },
};

export function formatComplaintPunishmentLabel(value: ComplaintPunishmentType): string {
    return COMPLAINT_COMMAND_RULES[value]?.label || value;
}

export function formatComplaintDurationLabel(
    value: ComplaintPunishmentType,
    duration: string | number | null | undefined,
): string {
    const rule = COMPLAINT_COMMAND_RULES[value];
    if (!rule.durationUnit) return 'Без срока';
    const parsed = Number(duration);
    if (!Number.isFinite(parsed) || parsed <= 0) return `0 ${rule.durationUnit}`;
    return `${parsed} ${rule.durationUnit}`;
}

export function formatComplaintStatusLabel(status: string | null | undefined): string {
    if (!status) return 'Черновик';
    return COMPLAINT_STATUS_LABELS[status] || status;
}

export function normalizeComplaintMedia(value: string | null | undefined): string {
    const normalized = String(value || '').trim();
    return normalized || '';
}

export function formatComplaintIncidentSuffix(value: string | null | undefined): string {
    const normalized = String(value || '').trim();
    const matched = normalized.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    if (matched) {
        return `${matched[4]}:${matched[5]} ${matched[3]}.${matched[2]}`;
    }
    return '00:00 00.00';
}

export function buildComplaintCommandLine(
    punishment: ComplaintPunishmentLike,
    context: ComplaintPreviewContext,
    actorName: string,
): string {
    const rule = COMPLAINT_COMMAND_RULES[punishment.punishment_type];
    const staticValue = String(punishment.static || '0');
    const reason = punishment.reason.trim();
    const suffix = `(media-жалоба ${normalizeComplaintMedia(context.media)} | ${formatComplaintIncidentSuffix(context.incident_at)})`;

    if (!rule.durationUnit) {
        return `${rule.command} ${staticValue} ${reason} ${suffix} by ${actorName}`.trim();
    }

    const duration = Number(punishment.duration || 0);
    return `${rule.command} ${staticValue} ${Number.isFinite(duration) ? duration : 0} ${reason} ${suffix} by ${actorName}`.trim();
}

export function buildComplaintMessageLine(punishment: ComplaintPunishmentLike): string {
    const rule = COMPLAINT_COMMAND_RULES[punishment.punishment_type];
    const label = rule.label;
    const reason = punishment.reason.trim();

    if (!rule.durationTextUnit) {
        return `Игрок #${punishment.static} получил ${label} за ${reason}`.trim();
    }

    const duration = Number(punishment.duration || 0);
    return `Игрок #${punishment.static} получил ${label} на ${Number.isFinite(duration) ? duration : 0} ${rule.durationTextUnit} за ${reason}`.trim();
}

export function buildComplaintAggregateCommand(
    punishments: ReadonlyArray<ComplaintPunishmentLike>,
    context: ComplaintPreviewContext,
    actorName: string,
): string {
    if (punishments.length === 0) return '—';
    return punishments
        .map((punishment) => buildComplaintCommandLine(punishment, context, actorName))
        .join('\n');
}

export function buildComplaintAggregateMessage(punishments: ReadonlyArray<ComplaintPunishmentLike>): string {
    if (punishments.length === 0) return '—';
    return punishments
        .map((punishment) => buildComplaintMessageLine(punishment))
        .join('\n');
}

export function buildComplaintCommandsPreview(
    punishments: ReadonlyArray<ComplaintPunishmentLike>,
    actorName: string,
    context: ComplaintPreviewContext,
): string {
    return buildComplaintAggregateCommand(punishments, context, actorName);
}

export function buildComplaintMessagesPreview(punishments: ReadonlyArray<ComplaintPunishmentLike>): string {
    return buildComplaintAggregateMessage(punishments);
}
