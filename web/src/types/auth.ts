export type KnownRole =
    | 'junior_employee'
    | 'employee'
    | 'senior_employee'
    | 'manager'
    | 'developer';

export type Role = KnownRole | (string & {});

export interface Permissions {
    [key: string]: boolean | undefined;
}

export interface UserContext {
    id: string;
    discord_id: string;
    username: string;
    nickname: string;
    role: Role;
    require_password_change: boolean;
    permissions: Permissions;
}

export interface OutletUserContext {
    user: UserContext | null;
    authResolved?: boolean;
}
