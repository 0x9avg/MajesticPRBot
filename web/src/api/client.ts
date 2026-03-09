/**
 * Centralized API client with silent refresh and single-flight mutex.
 *
 * Access token is stored in-memory only.
 * Refresh token is stored as an HttpOnly cookie (set by the API).
 *
 * Refresh strategy:
 *  - Proactive: before each request, if token expires within 60s, refresh preemptively
 *  - Reactive: on 401 TOKEN_EXPIRED / TOKEN_INVALID / SESSION_REVOKED → refresh and retry
 *  - Hard logout only on REFRESH_REUSE_DETECTED or when refresh itself fails
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ApiError {
    code?: string;
    message?: string;
    detail?: string | { code?: string; message?: string };
}

type LogoutCallback = () => void;

// ---------------------------------------------------------------------------
// In-memory token store
// ---------------------------------------------------------------------------

let _accessToken: string | null = null;
let _logoutCallback: LogoutCallback | null = null;

export function setAccessToken(token: string | null): void {
    _accessToken = token;
}

export function getAccessToken(): string | null {
    return _accessToken;
}

export function hydrateAccessTokenFromStorage(): string | null {
    return _accessToken;
}

/** Register a callback that will be invoked when a hard logout is required. */
export function onLogout(cb: LogoutCallback): void {
    _logoutCallback = cb;
}

function triggerLogout(): void {
    _accessToken = null;
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user');
    _logoutCallback?.();
}

// ---------------------------------------------------------------------------
// Token expiration helpers
// ---------------------------------------------------------------------------

/** Seconds until the current access token expires. Returns 0 if unparseable. */
function tokenExpiresInSeconds(token: string | null): number {
    if (!token) return 0;
    try {
        const parts = token.split('.');
        if (parts.length < 2) return 0;
        const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
        const padded = b64.padEnd(b64.length + ((4 - (b64.length % 4)) % 4), '=');
        const payload = JSON.parse(atob(padded)) as { exp?: number };
        if (!payload.exp) return 0;
        return payload.exp - Date.now() / 1000;
    } catch {
        return 0;
    }
}

// ---------------------------------------------------------------------------
// Single-flight refresh mutex
// ---------------------------------------------------------------------------

let _refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
    // If a refresh is already in-flight, piggyback on that promise
    if (_refreshPromise) {
        return _refreshPromise;
    }

    _refreshPromise = (async () => {
        try {
            const res = await fetch('/api/auth/refresh', {
                method: 'POST',
                credentials: 'include',  // send HttpOnly cookie
            });

            if (!res.ok) {
                return null;
            }

            const data = (await res.json()) as { access_token?: string };
            if (data.access_token) {
                setAccessToken(data.access_token);
                return data.access_token;
            }
            return null;
        } catch {
            return null;
        } finally {
            _refreshPromise = null;
        }
    })();

    return _refreshPromise;
}

/** Export for ProtectedRoute: attempt refresh and return whether it succeeded. */
export async function tryRefresh(): Promise<boolean> {
    const token = await refreshAccessToken();
    return token !== null;
}

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------

function getErrorCode(body: unknown): string | undefined {
    if (!body || typeof body !== 'object') return undefined;
    const b = body as ApiError;

    // Structured detail from our API: { detail: { code, message } }
    if (typeof b.detail === 'object' && b.detail !== null) {
        return (b.detail as { code?: string }).code;
    }
    return b.code;
}

/**
 * Fetch wrapper that:
 * 1. Proactively refreshes if token expires within 60s
 * 2. Attaches the in-memory access token
 * 3. On 401 TOKEN_EXPIRED / TOKEN_INVALID / SESSION_REVOKED → refreshes and retries once
 * 4. On REFRESH_REUSE_DETECTED or refresh failure → hard logout
 */
export async function apiFetch(
    url: string,
    init?: RequestInit,
): Promise<Response> {
    if (_accessToken) {
        const remaining = tokenExpiresInSeconds(_accessToken);
        if (remaining < 30) {
            await refreshAccessToken();
        }
    }

    const doFetch = (token: string | null) => {
        const headers = new Headers(init?.headers);
        if (token) {
            headers.set('Authorization', `Bearer ${token}`);
        }
        return fetch(url, {
            ...init,
            headers,
            credentials: 'include',  // always include cookies
        });
    };

    let response = await doFetch(_accessToken);

    if (response.status === 401) {
        // Clone the response so we can inspect the body without consuming it
        const cloned = response.clone();
        let errorBody: unknown = null;
        try {
            errorBody = await cloned.json();
        } catch {
            // Not JSON, treat as hard 401
        }

        const code = getErrorCode(errorBody);

        if (code === 'REFRESH_REUSE_DETECTED') {
            // Definite token theft — immediate hard logout, no retry
            triggerLogout();
        } else if (
            code === 'TOKEN_EXPIRED' ||
            code === 'TOKEN_INVALID' ||
            code === 'SESSION_REVOKED'
        ) {
            // All these cases can be resolved by a fresh refresh token rotation.
            // SESSION_REVOKED typically means the old session was replaced during
            // a previous rotation — the refresh cookie still holds the latest token.
            const newToken = await refreshAccessToken();
            if (newToken) {
                // Retry the original request once with the new access token
                response = await doFetch(newToken);
            } else {
                // Refresh failed — hard logout
                triggerLogout();
            }
        } else {
            // Unknown 401 code — hard logout
            triggerLogout();
        }
    }

    return response;
}

// ---------------------------------------------------------------------------
// Convenience helpers
// ---------------------------------------------------------------------------

export async function apiGet<T = unknown>(url: string): Promise<T> {
    const res = await apiFetch(url);
    if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
            (body as ApiError).detail?.toString() ||
            (body as ApiError).message ||
            `HTTP ${res.status}`,
        );
    }
    return res.json() as Promise<T>;
}

export async function apiPost<T = unknown>(url: string, data?: unknown): Promise<T> {
    const res = await apiFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: data !== undefined ? JSON.stringify(data) : undefined,
    });
    if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
            (body as ApiError).detail?.toString() ||
            (body as ApiError).message ||
            `HTTP ${res.status}`,
        );
    }
    return res.json() as Promise<T>;
}
