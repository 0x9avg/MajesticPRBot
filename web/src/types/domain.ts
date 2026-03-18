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
    gross_points?: number;
    net_points?: number;
    active_point_penalty?: number;
    active_percent_penalty?: number;
    active_checks?: number;
    active_warning_units?: number;
    active_strict_warnings?: number;
    active_oral_warnings?: number;
    active_warnings_display?: string;
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
    assigned_at?: string | null;
}

export interface Streamer {
    streamer_id: string;
    streamer_name: string;
    priority: number;
    pr_slots: number;
    current_stream_priority_override?: number | null;
    current_stream_pr_slots_override?: number | null;
    is_pinned?: boolean;
    is_online?: boolean;
    allow_juniors?: boolean;
    profile_image_url?: string | null;
    stream_thumbnail_url?: string | null;
    game_id?: string | null;
    game_name?: string | null;
    assignments?: StreamerAssignment[];
}

export interface SanctionDayStatus {
    assistant_id: string;
    work_date: string;
    spec_seconds_on_day: number;
    spec_hours_on_day: number;
    spec_points_auto: number;
    manual_points_delta: number;
    mchat_count: number;
    complaints_count: number;
    check_immunity: boolean;
    point_immunity: boolean;
    percent_immunity: boolean;
    streak_check_days: number;
    streak_point_days: number;
    streak_percent_days: number;
}

export interface SanctionSummary {
    assistant_id: string;
    as_of_date: string;
    check: number;
    point: number;
    percent: number;
    oral: number;
    strict: number;
    warnings_units: number;
    strict_warnings: number;
    oral_warnings: number;
    warnings_display: string;
}

export interface WorkoffItem {
    id?: string;
    sanction_id?: string;
    operation_id?: string;
    metric: 'spec' | 'complaints' | 'mchat';
    multiplier: number;
    period_start: string;
    period_end: string;
    target_amount?: number;
    amount_done?: number;
    remaining_amount?: number;
    is_completed?: boolean;
}

export interface ActiveSanction {
    sanction_id: string;
    assistant_id: string;
    kind: 'check' | 'point' | 'percent' | 'oral' | 'strict';
    amount_total: number;
    relieved_amount: number;
    active_amount: number;
    issued_at: string;
    display_issued_at?: string | null;
    source_type: 'manual' | 'queued_batch' | 'check_cycle' | 'legacy_migration';
    operation_id?: string | null;
    basis_date?: string | null;
    settings_month?: string | null;
    check_rule_hit_no?: number | null;
    auto_relief_date?: string | null;
    workoff_items: WorkoffItem[];
    workoff_progress_summary: {
        has_workoff: boolean;
        total_items: number;
        completed_items: number;
        items: WorkoffItem[];
    };
}

export interface SanctionOperationMember {
    operation_id: string;
    assistant_id: string;
    nickname?: string | null;
    issue_status: 'pending' | 'issued' | 'skipped_immunity' | 'failed';
    issue_reason?: string | null;
    issued_sanction_id?: string | null;
}

export interface SanctionOperation {
    id: string;
    operation_date: string;
    created_at: string;
    queued_at?: string | null;
    created_by_id?: string | null;
    created_by_name?: string | null;
    penalty_kind: 'check' | 'point' | 'percent' | 'oral' | 'strict';
    penalty_amount: number;
    auto_relief_date?: string | null;
    recipient_mode: 'all_active' | 'live_without_active_session' | 'selected_only';
    workoff_items?: WorkoffItem[];
    status: 'queued' | 'processing' | 'completed' | 'cancelled' | 'failed';
    processing_mode?: 'manual_now' | 'nightly_auto' | null;
    processed_by_id?: string | null;
    processed_by_name?: string | null;
    processed_at?: string | null;
    cancelled_at?: string | null;
    failure_reason?: string | null;
    members_total?: number;
    effective_members?: number;
    issued_members?: number;
    skipped_immunity_members?: number;
    members?: SanctionOperationMember[];
}

export interface MonthlySanctionSettings {
    check_cycle_size: number;
    check_immunity_hours_per_day: number;
    point_immunity_hours_per_day: number;
    percent_immunity_hours_per_day: number;
    check_relief_hours_per_day: number;
    point_relief_hours_per_day: number;
    percent_relief_hours_per_day: number;
    check_relief_min_streak_days: number;
    point_relief_min_streak_days: number;
    percent_relief_min_streak_days: number;
    percent_relief_step_amount: number;
    daily_norm_spec: number;
    daily_norm_complaints: number;
    daily_norm_mchat: number;
}

export interface MonthlyCheckRule {
    id?: string;
    range_start: number;
    range_end: number | null;
    penalty_kind: 'point' | 'percent' | 'oral' | 'strict';
    penalty_amount: number;
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
