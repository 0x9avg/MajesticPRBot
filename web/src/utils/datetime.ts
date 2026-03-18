/**
 * Parse a datetime string from the API as MSK.
 * API returns datetimes without timezone suffix (e.g. "2026-02-28T10:00:00").
 * Without '+03:00', browsers treat this as local time — causing timezone drift.
 * This function appends '+03:00' when no timezone indicator is present to explicitly mark it as Moscow Time.
 */
export const parseMskDate = (value: string | null | undefined): Date | null => {
    if (!value) return null;

    let dateStr = value;
    // If it's just a date (YYYY-MM-DD), append time to allow timezone addition
    if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
        dateStr += 'T00:00:00';
    }

    const hasTimezone = /Z$|[+-]\d{2}:\d{2}$/.test(dateStr);
    const dt = new Date(hasTimezone ? dateStr : dateStr + '+03:00');
    return Number.isNaN(dt.getTime()) ? null : dt;
};

/**
 * Format a MSK datetime string from the API to local display.
 * Returns '—' for empty/invalid values.
 */
export const formatMskToLocal = (
    value: string | null | undefined,
    options?: Intl.DateTimeFormatOptions,
): string => {
    const dt = parseMskDate(value);
    if (!dt) return '—';

    const defaultOptions: Intl.DateTimeFormatOptions = {
        timeZone: 'Europe/Moscow',
    };

    if (!options) {
        Object.assign(defaultOptions, {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    return dt.toLocaleString('ru-RU', {
        ...defaultOptions,
        ...options,
    });
};
/**
 * Returns a new Date object representing the current moment in Moscow Time.
 * Note: This creates a Date object whose internal UTC time is shifted to match MSK wall-clock time.
 * Use ONLY for default values in inputs/view logic, NOT for arithmetic across timezones.
 */
export const getMskNow = (): Date => {
    // Current UTC time + 3 hours
    const now = new Date();
    return new Date(now.getTime() + 3 * 60 * 60 * 1000);
};

/**
 * Returns the current date in Moscow in YYYY-MM-DD format (ISO 8601).
 */
export const getMskTodayStr = (): string => {
    const now = new Date();
    // Use Intl to format specifically for MSK and extract the date part
    const formatter = new Intl.DateTimeFormat('sv-SE', {
        timeZone: 'Europe/Moscow',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    });
    return formatter.format(now);
};

/**
 * Returns a Moscow date shifted by N days from today in YYYY-MM-DD format.
 */
export const getMskDateOffsetStr = (days: number): string => {
    const base = parseMskDate(getMskTodayStr()) ?? new Date();
    base.setUTCDate(base.getUTCDate() + days);
    return formatToMskIso(base).slice(0, 10);
};

/**
 * Formats a Date object specifically to 'YYYY-MM-DDTHH:mm:ss' in MSK.
 */
export const formatToMskIso = (date: Date): string => {
    const formatter = new Intl.DateTimeFormat('sv-SE', {
        timeZone: 'Europe/Moscow',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
    const parts = formatter.formatToParts(date);
    const getPart = (type: string) => parts.find(p => p.type === type)?.value || '';
    return `${getPart('year')}-${getPart('month')}-${getPart('day')}T${getPart('hour')}:${getPart('minute')}:${getPart('second')}`;
};
