import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CustomSelect } from '../CustomInputs';

describe('CustomSelect', () => {
    it('selects a single value and closes dropdown', async () => {
        const onChange = vi.fn();
        const ui = userEvent.setup();

        render(
            <CustomSelect
                value=""
                onChange={onChange}
                options={[
                    { value: 'one', label: 'One' },
                    { value: 'two', label: 'Two' },
                ]}
                placeholder="Pick one"
            />
        );

        await ui.click(screen.getByText('Pick one'));
        await ui.click(screen.getByText('One'));

        expect(onChange).toHaveBeenCalledWith('one');
        expect(screen.queryByText('Two')).not.toBeInTheDocument();
    });

    it('supports multi-select and reset option', async () => {
        const onChange = vi.fn();
        const ui = userEvent.setup();

        render(
            <CustomSelect
                value={[]}
                onChange={onChange}
                options={[
                    { value: '', label: 'All' },
                    { value: 'one', label: 'One' },
                    { value: 'two', label: 'Two' },
                ]}
                placeholder="Pick many"
                multiple
            />
        );

        await ui.click(screen.getByText('Pick many'));
        await ui.click(screen.getByText('One'));
        expect(onChange).toHaveBeenCalledWith(['one']);

        await ui.click(screen.getByText('All'));
        expect(onChange).toHaveBeenCalledWith([]);
    });
});
