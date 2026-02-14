export type KnownRole =
    | 'junior_employee'
    | 'employee'
    | 'senior_employee'
    | 'manager'
    | 'developer';

export type Role = KnownRole | (string & {});

export interface Permissions {
    can_register_users?: boolean;
    can_view_admin_logs?: boolean;
    [key: string]: boolean | undefined;
}

export interface UserContext {
    id: number;
    discord_id: string;
    username: string;
    nickname: string;
    role: Role;
    require_password_change: boolean;
    permissions: Permissions;
}

export interface OutletUserContext {
    user: UserContext | null;
}
