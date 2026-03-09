export interface Assistant {
    pr_id: string;
    nickname: string;
    role: string;
    experience_days: number;
    appointed_at?: string | null;
    added_at?: string | null;
    updated_at?: string | null;
    status?: string;
    assigned_to_type?: 'streamer' | 'event' | null;
    assigned_to_name?: string | null;
    total_spec_seconds?: number;
    total_spec_hours?: number;
    total_spec_hours_30d?: number;
    avg_spec_hours_per_day_30d?: number;
    session_count?: number;
    auto_points_total?: number;
    manual_points_adjustment?: number;
    total_points?: number;
    penalty_points?: number;
    penalty_percent?: number;
    display_points?: number;
    warnings_units?: number;
    strict_warnings?: number;
    oral_warnings?: number;
    warnings_display?: string;
}

export interface AssistantLog {
    id: string;
    action: string;
    target?: string | null;
    created_at: string;
    duration_seconds?: number | null;
    duration?: string | null;
}

export interface StreamerAssignment {
    pr_id: string;
    nickname?: string;
    is_probation?: boolean;
}

export interface Streamer {
    streamer_id: string;
    streamer_name: string;
    priority: number;
    pr_slots: number;
    priority_override?: number | null;
    pr_slots_override?: number | null;
    is_pinned?: boolean;
    is_online?: boolean;
    allow_juniors?: boolean;
    profile_image_url?: string | null;
    stream_thumbnail_url?: string | null;
    game_id?: string | null;
    game_name?: string | null;
    assignments?: StreamerAssignment[];
    assigned_pr_id?: string | null;
}

export interface EventParticipant {
    pr_id: string;
    nickname: string | null;
    status?: string | null;
}

export interface Event {
    id: string;
    name: string;
    description?: string;
    priority?: number;
    is_pinned?: boolean;
    is_active?: boolean;
    pr_slots?: number;
    required_pr_count?: number;
    current_participants?: number;
    participants?: EventParticipant[];
    start_time?: string | null;
    event_kind?: 'regular' | 'spec_request';
    approval_status?: 'approved' | 'pending' | 'rejected';
    requested_by?: string | null;
    approved_by?: string | null;
    approved_at?: string | null;
    rejected_by?: string | null;
    rejected_at?: string | null;
}

export interface DashboardStats {
    assigned_pr_count: number;
    unassigned_media_count: number;
    events_today_count: number;
}

export interface AdminLogRecord {
    id: string;
    actor_id?: string | null;
    actor_name: string;
    actor_role?: string | null;
    admin_name?: string;
    admin_role?: string | null;
    action: string;
    kind?: string;
    target_name?: string | null;
    target_id?: string | null;
    target_type?: string | null;
    details?: {
        summary?: string;
        changes?: Record<string, unknown>;
        payload?: Record<string, unknown>;
        meta?: Record<string, unknown>;
        [key: string]: unknown;
    } | null;
    created_at: string;
}

export type PunishmentType = 'jail' | 'mute';
export type PunishmentReturnStatus = 'pending' | 'claimed' | 'completed';
export type PunishmentReturnReason = 'На стрим' | 'На видео';

export interface PunishmentReturnQueueItem {
    id: string;
    punishment_type: PunishmentType;
    static: number;
    server: number;
    duration: number;
    remove_reason: PunishmentReturnReason;
    discord_message_url: string | null;
    removed_by_id: string;
    removed_by_name: string;
    removed_at: string;
    claimed_by_id?: string | null;
    claimed_by_name?: string | null;
    claimed_at?: string | null;
    completed_by_id?: string | null;
    completed_by_name?: string | null;
    completed_at?: string | null;
    status: PunishmentReturnStatus;
    status_label: string;
    remove_command: string;
    return_command: string;
    can_claim: boolean;
    can_complete: boolean;
    can_release: boolean;
    can_edit: boolean;
    can_delete: boolean;
}

export type PunishmentReturnHistoryItem = PunishmentReturnQueueItem;

export interface PunishmentReturnCreateInput {
    punishment_type: PunishmentType;
    static: number;
    server: number;
    duration: number;
    remove_reason: PunishmentReturnReason;
    discord_message_url?: string | null;
}

export interface PunishmentReturnUpdateInput {
    punishment_type?: PunishmentType;
    static?: number;
    server?: number;
    duration?: number;
    remove_reason?: PunishmentReturnReason;
    discord_message_url?: string | null;
}
