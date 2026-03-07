export interface ApiFieldError {
    field: string;
    reason: string;
}

export interface ApiEnvelope<T> {
    status?: string;
    code?: string;
    message?: string;
    data?: T;
    errors?: ApiFieldError[];
    trace_id?: string;
}

const hasDataField = <T>(value: unknown): value is ApiEnvelope<T> => {
    return !!value && typeof value === 'object' && 'data' in value;
};

export const unwrapApiData = <T>(value: unknown): T => {
    if (hasDataField<T>(value)) {
        return value.data as T;
    }
    return value as T;
};

type ErrorWithDetail = {
    detail?: string | {
        code?: string;
        message?: string;
    };
    message?: string;
    errors?: ApiFieldError[];
};

export const getApiErrorMessage = (
    payload: unknown,
    fallback = 'Произошла ошибка'
): string => {
    if (!payload || typeof payload !== 'object') {
        return fallback;
    }

    const data = payload as ErrorWithDetail;
    const detail = data.detail;
    const detailMessage = detail && typeof detail === 'object'
        ? detail.message
        : undefined;
    const detailString = typeof detail === 'string' ? detail : undefined;

    return (
        detailMessage ||
        detailString ||
        data.message ||
        data.errors?.[0]?.reason ||
        fallback
    );
};
