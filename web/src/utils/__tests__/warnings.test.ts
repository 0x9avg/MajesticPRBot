import { describe, expect, it } from 'vitest';

import { formatAssistantWarnings } from '../warnings';

describe('formatAssistantWarnings', () => {
    it('formats canonical warning counters into legacy display string', () => {
        expect(formatAssistantWarnings(1, 0)).toBe('1/2 0/2');
        expect(formatAssistantWarnings(0, 1)).toBe('0/2 1/2');
    });

    it('defaults missing or invalid values to zero', () => {
        expect(formatAssistantWarnings(undefined, null)).toBe('0/2 0/2');
        expect(formatAssistantWarnings(-1, -2)).toBe('0/2 0/2');
    });
});
