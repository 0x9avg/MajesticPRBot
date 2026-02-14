import { describe, it, expect } from 'vitest';
import { getApiErrorMessage, unwrapApiData } from '../api';

describe('api utils', () => {
    it('unwraps envelope data when data key exists', () => {
        const payload = { status: 'success', data: { value: 42 } };
        expect(unwrapApiData<{ value: number }>(payload)).toEqual({ value: 42 });
    });

    it('returns payload as-is when envelope data key is missing', () => {
        const payload = [{ id: 1 }];
        expect(unwrapApiData<{ id: number }[]>(payload)).toEqual([{ id: 1 }]);
    });

    it('extracts detail/message/errors in priority order', () => {
        expect(getApiErrorMessage({ detail: 'detail error' }, 'fallback')).toBe('detail error');
        expect(getApiErrorMessage({ message: 'message error' }, 'fallback')).toBe('message error');
        expect(
            getApiErrorMessage({ errors: [{ field: 'x', reason: 'reason error' }] }, 'fallback')
        ).toBe('reason error');
    });

    it('falls back when payload is invalid', () => {
        expect(getApiErrorMessage(null, 'fallback')).toBe('fallback');
        expect(getApiErrorMessage(undefined, 'fallback')).toBe('fallback');
        expect(getApiErrorMessage('oops', 'fallback')).toBe('fallback');
    });
});
