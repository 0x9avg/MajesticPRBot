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

export type WorkoffOverrideStatus = 'P' | 'U' | 'O' | null;
export type WorkoffProgressStatus = 'pending' | 'completed' | 'failed' | 'leave_skipped' | string;

export interface WorkoffProgressDay {
    date: string;
    manual_status?: WorkoffOverrideStatus;
    counts_for_workoff?: boolean;
    required_amount?: number;
    actual_amount?: number;
    day_status?: WorkoffProgressStatus;
}

export interface WorkoffProgressItem {
    metric: 'spec' | 'complaints' | 'mchat';
    multiplier: number;
    period_start: string;
    period_end: string;
    required_work_days?: number;
    counted_work_days?: number;
    effective_period_end?: string | null;
    uo_days_count?: number;
    status?: WorkoffProgressStatus;
    days?: WorkoffProgressDay[];
    target_amount?: number;
    amount_done?: number;
    remaining_amount?: number;
    is_completed?: boolean;
}

export interface WorkoffPreviewAssistant {
    assistant_id: string;
    nickname?: string | null;
    items: WorkoffProgressItem[];
}

export interface WorkoffPreviewResponse {
    assistants?: WorkoffPreviewAssistant[];
    items?: WorkoffPreviewAssistant[];
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
    required_work_days?: number;
    counted_work_days?: number;
    effective_period_end?: string | null;
    uo_days_count?: number;
    status?: WorkoffProgressStatus;
    days?: WorkoffProgressDay[];
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
    issue_status: 'pending' | 'issued' | 'skipped_immunity' | 'skipped_leave' | 'failed';
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
    skipped_leave_members?: number;
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

export type WeeklyDayStatus = 'P' | 'U' | 'O';
export type WeeklySuggestedResult = 'Ультра-Актив' | 'Актив' | 'Инактив/Актив' | 'Инактив';
export type WeeklySelectedResult = WeeklySuggestedResult | 'Актив/Отпуск' | 'Инактив/Отпуск' | 'Отпуск';
export type WeeklyPayoutType = 'EXP' | 'Premium' | 'MC' | 'MONEY';
export type WeeklyPayoutIssueStatus = 'pending' | 'issued';
export type WeeklyPayoutServer = string;
export type WeeklyStatusSource = 'manual' | 'auto' | 'none';
export type WeeklyPayoutReason =
    | 'selected_result_not_payout_eligible'
    | 'incomplete_payout_data'
    | 'payout_type_rule_missing'
    | 'amount_rule_missing'
    | string;

export interface WeeklyApiDayHeader {
    work_date: string;
    weekday_index: number;
    weekday_short: string;
    label_short: string;
}

export interface WeeklyApiDay {
    work_date: string;
    weekday_index: number;
    is_roster_day: boolean;
    spec_seconds: number;
    spec_hours: number;
    mchat_count: number;
    complaints_count: number;
    daily_norm_spec: number;
    daily_norm_mchat: number;
    daily_norm_complaints: number;
    manual_status: WeeklyDayStatus | null;
    auto_status: WeeklyDayStatus | null;
    resolved_status: WeeklyDayStatus | null;
    status_source: WeeklyStatusSource;
    manual_status_updated_at?: string | null;
    manual_status_updated_by_id?: string | null;
}

export interface WeeklyApiPayout {
    type: WeeklyPayoutType | null;
    server: WeeklyPayoutServer | null;
    static: string | null;
    command_name?: string | null;
    amount?: string | null;
    command: string | null;
    command_available: boolean;
    command_unavailable_reason: WeeklyPayoutReason | null;
    role_group?: string | null;
}

export interface WeeklyApiAssistantItem {
    assistant_id: string;
    nickname: string;
    role: string;
    week_start: string;
    week_end: string;
    days?: WeeklyApiDay[];
    totals: {
        spec_hours: number;
        mchat_count: number;
        complaints_count: number;
    };
    counts: {
        P: number;
        U: number;
        O: number;
    };
    suggested_result: WeeklySuggestedResult | null;
    suggested_reason: string | null;
    suggestion_metrics?: {
        metric_hits: number;
        weekly_norm_spec: number;
        weekly_norm_mchat: number;
        weekly_norm_complaints: number;
    };
    selected_result: WeeklySelectedResult | null;
    result_display: WeeklySelectedResult | WeeklySuggestedResult | null;
    payout: WeeklyApiPayout;
    payout_issue_status?: WeeklyPayoutIssueStatus;
    payout_issued_at?: string | null;
    payout_issued_by_id?: string | null;
    review_updated_at?: string | null;
    review_updated_by_id?: string | null;
}

export interface WeeklyApiPayoutOptions {
    types: Array<{ value: WeeklyPayoutType; command_name: string }>;
    servers: WeeklyPayoutServer[];
    selected_results: WeeklySelectedResult[];
    manual_statuses: WeeklyDayStatus[];
}

export interface WeeklyAssistantDay {
    work_date: string;
    weekday_label?: string;
    spec_hours_on_day: number;
    mchat_count: number;
    complaints_count: number;
    manual_status: WeeklyDayStatus | null;
    auto_status: WeeklyDayStatus | null;
    resolved_status: WeeklyDayStatus | null;
    status_source: WeeklyStatusSource;
}

export interface WeeklyAssistantSummary {
    assistant_id: string;
    nickname: string;
    role: string;
    week_start: string;
    week_end: string;
    days: WeeklyAssistantDay[];
    total_spec_hours: number;
    total_mchat: number;
    total_complaints: number;
    suggested_result: WeeklySuggestedResult | null;
    selected_result: WeeklySelectedResult | null;
    result_display: WeeklySelectedResult | WeeklySuggestedResult | null;
    count_P: number;
    count_U: number;
    count_O: number;
    payout_type: WeeklyPayoutType | null;
    payout_server: WeeklyPayoutServer | null;
    payout_static: string | null;
    payout_issue_status: WeeklyPayoutIssueStatus;
    payout_issued_at: string | null;
    payout_issued_by_id: string | null;
    generated_payout_command: string | null;
    generated_payout_available: boolean;
    generated_payout_reason: string | null;
}

export interface WeeklyCurrentResponse {
    week_start: string;
    week_end: string;
    day_labels: { work_date: string; label: string }[];
    items: WeeklyAssistantSummary[];
}

export interface WeeklyCurrentApiResponse {
    week_start: string;
    week_end: string;
    day_headers: WeeklyApiDayHeader[];
    items: WeeklyApiAssistantItem[];
}

export interface WeeklyAdminListResponse {
    week_start: string;
    week_end: string;
    day_labels: { work_date: string; label: string }[];
    items: WeeklyAssistantSummary[];
    payout_types: { value: WeeklyPayoutType; label: string }[];
    payout_servers: WeeklyPayoutServer[];
    result_options: WeeklySelectedResult[];
}

export interface WeeklyAdminListApiResponse {
    week_start: string;
    week_end: string;
    day_headers: WeeklyApiDayHeader[];
    items: WeeklyApiAssistantItem[];
    payout_options: WeeklyApiPayoutOptions;
}

export interface WeeklyAssistantDetail extends WeeklyAssistantSummary {
    day_overrides: { work_date: string; manual_status: WeeklyDayStatus | null; is_manual_override: boolean }[];
}

export interface WeeklyAssistantDetailApiResponse {
    week_start: string;
    week_end: string;
    day_headers: WeeklyApiDayHeader[];
    payout_options: WeeklyApiPayoutOptions;
    detail: WeeklyApiAssistantItem & { days: WeeklyApiDay[] };
}

export interface WeeklyAssistantSaveRequest {
    day_overrides: { work_date: string; manual_status: WeeklyDayStatus | null; is_manual_override: boolean }[];
    selected_result: WeeklySelectedResult | null;
    payout_type: WeeklyPayoutType | null;
    payout_server: WeeklyPayoutServer | null;
    payout_static: string | null;
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
