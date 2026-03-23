import React from 'react';

import { apiFetch } from '../../../../api/client';
import { unwrapApiData } from '../../../../types/api';
import type {
    ActiveSanction,
    Assistant,
    AssistantSessionRecord,
    AssistantSessionTargetsResponse,
    SanctionDayStatus,
} from '../../../../types/domain';

async function loadJson<T>(url: string): Promise<T> {
    const response = await apiFetch(url);
    const payload = await response.json().catch(() => ({} as unknown));
    if (!response.ok) {
        throw new Error((payload as { detail?: string }).detail || 'Не удалось загрузить данные');
    }
    return unwrapApiData<T>(payload);
}

function useRequestGuard() {
    const requestIdRef = React.useRef(0);

    return React.useCallback(() => {
        requestIdRef.current += 1;
        return requestIdRef.current;
    }, []);
}

export function useAssistantsList(enabled = true) {
    const [assistants, setAssistants] = React.useState<Assistant[]>([]);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState<string | null>(null);
    const nextRequestId = useRequestGuard();
    const activeRequestIdRef = React.useRef(0);

    const reload = React.useCallback(async () => {
        if (!enabled) {
            activeRequestIdRef.current += 1;
            setAssistants([]);
            setLoading(false);
            setError(null);
            return;
        }

        const requestId = nextRequestId();
        activeRequestIdRef.current = requestId;
        setLoading(true);
        setError(null);

        try {
            const data = await loadJson<Assistant[] | { assistants?: Assistant[] }>('/api/assistants');
            if (activeRequestIdRef.current !== requestId) return;
            const normalized = Array.isArray(data) ? data : data.assistants;
            setAssistants(Array.isArray(normalized) ? normalized : []);
        } catch (err) {
            if (activeRequestIdRef.current !== requestId) return;
            setAssistants([]);
            setError(err instanceof Error ? err.message : 'Не удалось загрузить ассистентов');
        } finally {
            if (activeRequestIdRef.current === requestId) {
                setLoading(false);
            }
        }
    }, [enabled, nextRequestId]);

    React.useEffect(() => {
        void reload();
    }, [reload]);

    return { assistants, loading, error, reload };
}

export function useAssistantDetail(prId: string | null, enabled: boolean) {
    const [assistant, setAssistant] = React.useState<Assistant | null>(null);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState<string | null>(null);
    const nextRequestId = useRequestGuard();
    const activeRequestIdRef = React.useRef(0);

    const reload = React.useCallback(async () => {
        if (!prId || !enabled) {
            activeRequestIdRef.current += 1;
            setAssistant(null);
            setLoading(false);
            setError(null);
            return;
        }

        const requestId = nextRequestId();
        activeRequestIdRef.current = requestId;
        setLoading(true);
        setError(null);

        try {
            const data = await loadJson<Assistant>(`/api/assistants/${prId}`);
            if (activeRequestIdRef.current !== requestId) return;
            setAssistant(data);
        } catch (err) {
            if (activeRequestIdRef.current !== requestId) return;
            setAssistant(null);
            setError(err instanceof Error ? err.message : 'Не удалось загрузить профиль ассистента');
        } finally {
            if (activeRequestIdRef.current === requestId) {
                setLoading(false);
            }
        }
    }, [enabled, nextRequestId, prId]);

    React.useEffect(() => {
        void reload();
    }, [reload]);

    return { assistant, loading, error, reload, setAssistant };
}

export function useAssistantSessions(prId: string | null, enabled: boolean) {
    const [sessions, setSessions] = React.useState<AssistantSessionRecord[]>([]);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState<string | null>(null);
    const nextRequestId = useRequestGuard();
    const activeRequestIdRef = React.useRef(0);

    const reload = React.useCallback(async () => {
        if (!prId || !enabled) {
            activeRequestIdRef.current += 1;
            setSessions([]);
            setLoading(false);
            setError(null);
            return;
        }

        const requestId = nextRequestId();
        activeRequestIdRef.current = requestId;
        setLoading(true);
        setError(null);

        try {
            const data = await loadJson<AssistantSessionRecord[]>(`/api/assistants/${prId}/sessions?limit=50`);
            if (activeRequestIdRef.current !== requestId) return;
            setSessions(Array.isArray(data) ? data : []);
        } catch (err) {
            if (activeRequestIdRef.current !== requestId) return;
            setSessions([]);
            setError(err instanceof Error ? err.message : 'Не удалось загрузить сессии ассистента');
        } finally {
            if (activeRequestIdRef.current === requestId) {
                setLoading(false);
            }
        }
    }, [enabled, nextRequestId, prId]);

    React.useEffect(() => {
        void reload();
    }, [reload]);

    return { sessions, loading, error, reload, setSessions };
}

export function useAssistantSanctions(prId: string | null, enabled: boolean) {
    const [sanctions, setSanctions] = React.useState<ActiveSanction[]>([]);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState<string | null>(null);
    const nextRequestId = useRequestGuard();
    const activeRequestIdRef = React.useRef(0);

    const reload = React.useCallback(async () => {
        if (!prId || !enabled) {
            activeRequestIdRef.current += 1;
            setSanctions([]);
            setLoading(false);
            setError(null);
            return;
        }

        const requestId = nextRequestId();
        activeRequestIdRef.current = requestId;
        setLoading(true);
        setError(null);

        try {
            const data = await loadJson<ActiveSanction[]>(`/api/assistants/${prId}/sanctions/active`);
            if (activeRequestIdRef.current !== requestId) return;
            setSanctions(Array.isArray(data) ? data : []);
        } catch (err) {
            if (activeRequestIdRef.current !== requestId) return;
            setSanctions([]);
            setError(err instanceof Error ? err.message : 'Не удалось загрузить активные санкции ассистента');
        } finally {
            if (activeRequestIdRef.current === requestId) {
                setLoading(false);
            }
        }
    }, [enabled, nextRequestId, prId]);

    React.useEffect(() => {
        void reload();
    }, [reload]);

    return { sanctions, loading, error, reload, setSanctions };
}

export function useAssistantDayStatus(
    prId: string | null,
    workDate: string,
    enabled: boolean,
) {
    const [dayStatus, setDayStatus] = React.useState<SanctionDayStatus | null>(null);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState<string | null>(null);
    const nextRequestId = useRequestGuard();
    const activeRequestIdRef = React.useRef(0);

    const reload = React.useCallback(async () => {
        if (!prId || !enabled) {
            activeRequestIdRef.current += 1;
            setDayStatus(null);
            setLoading(false);
            setError(null);
            return;
        }

        const requestId = nextRequestId();
        activeRequestIdRef.current = requestId;
        setLoading(true);
        setError(null);

        try {
            const data = await loadJson<SanctionDayStatus>(`/api/assistants/${prId}/day-status?date=${workDate}`);
            if (activeRequestIdRef.current !== requestId) return;
            setDayStatus(data);
        } catch (err) {
            if (activeRequestIdRef.current !== requestId) return;
            setDayStatus(null);
            setError(err instanceof Error ? err.message : 'Не удалось загрузить дневной статус ассистента');
        } finally {
            if (activeRequestIdRef.current === requestId) {
                setLoading(false);
            }
        }
    }, [enabled, nextRequestId, prId, workDate]);

    React.useEffect(() => {
        void reload();
    }, [reload]);

    return { dayStatus, loading, error, reload, setDayStatus };
}

export function useSessionTargets(enabled: boolean) {
    const [data, setData] = React.useState<AssistantSessionTargetsResponse | null>(null);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState<string | null>(null);
    const nextRequestId = useRequestGuard();
    const activeRequestIdRef = React.useRef(0);

    const ensureLoaded = React.useCallback(async () => {
        if (!enabled) {
            setData(null);
            setLoading(false);
            setError(null);
            return null;
        }
        if (data) {
            return data;
        }

        const requestId = nextRequestId();
        activeRequestIdRef.current = requestId;
        setLoading(true);
        setError(null);

        try {
            const nextData = await loadJson<AssistantSessionTargetsResponse>('/api/assistants/session-targets');
            if (activeRequestIdRef.current !== requestId) {
                return null;
            }
            setData(nextData);
            return nextData;
        } catch (err) {
            if (activeRequestIdRef.current !== requestId) {
                return null;
            }
            setError(err instanceof Error ? err.message : 'Не удалось загрузить цели для сессий');
            return null;
        } finally {
            if (activeRequestIdRef.current === requestId) {
                setLoading(false);
            }
        }
    }, [data, enabled, nextRequestId]);

    const reset = React.useCallback(() => {
        activeRequestIdRef.current += 1;
        setData(null);
        setLoading(false);
        setError(null);
    }, []);

    return {
        data,
        loading,
        error,
        ensureLoaded,
        reset,
    };
}
