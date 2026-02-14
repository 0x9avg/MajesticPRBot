export interface Assistant {
    pr_id: number;
    nickname: string;
    role: string;
    experience_days: number;
    status?: string;
    assigned_to_type?: 'streamer' | 'event' | null;
    assigned_to_name?: string | null;
    total_spec_seconds?: number;
    total_spec_hours?: number;
    session_count?: number;
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
    admin_name: string;
    admin_role?: string;
    action: string;
    target_name?: string | null;
    target_id?: string | number | null;
    target_type?: string | null;
    details?: Record<string, unknown> | null;
    created_at: string;
}
