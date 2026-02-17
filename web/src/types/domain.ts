export interface Assistant {
    pr_id: number;
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
    id: number | string;
    action: string;
    target?: string | null;
    created_at: string;
    duration_seconds?: number | null;
    duration?: string | null;
}

export interface StreamerAssignment {
    pr_id: number | string;
    nickname?: string;
}

export interface Streamer {
    streamer_id: number;
    streamer_name: string;
    priority: number;
    pr_slots: number;
    is_pinned?: boolean;
    is_online?: boolean;
    profile_image_url?: string | null;
    stream_thumbnail_url?: string | null;
    stream_points_override?: number | null;
    game_name?: string | null;
    assignments?: StreamerAssignment[];
    assigned_pr_id?: number | null;
}

export interface EventParticipant {
    pr_id: number | string;
    nickname: string;
}

export interface Event {
    id: number;
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
}

export interface DashboardStats {
    assigned_pr_count: number;
    unassigned_media_count: number;
    events_today_count: number;
}

export interface AdminLogRecord {
    id: number;
    actor_name: string;
    actor_role?: string | null;
    admin_name?: string;
    admin_role?: string | null;
    action: string;
    kind?: string;
    target_name?: string | null;
    target_id?: string | number | null;
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
