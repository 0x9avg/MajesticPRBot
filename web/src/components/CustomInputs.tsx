import React, { useState, useEffect, useRef } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, X, Calendar as CalendarIcon, Check, Clock } from 'lucide-react';

// ==========================================
// Custom Select Component
// ==========================================
interface CustomSelectProps {
    value: string | string[];
    onChange: (value: string | string[]) => void;
    options: { value: string; label: string }[];
    placeholder?: string;
    icon?: React.ReactNode;
    multiple?: boolean;
}

export const CustomSelect = ({ value, onChange, options, placeholder = "Select...", icon, multiple = false }: CustomSelectProps) => {
    const [isOpen, setIsOpen] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const getDisplayLabel = () => {
        if (multiple && Array.isArray(value)) {
            if (value.length === 0) return placeholder;
            if (value.length === 1) return options.find(o => o.value === value[0])?.label || placeholder;
            return `${value.length} выбрано`;
        }
        return options.find(opt => opt.value === value)?.label || placeholder;
    };

    const handleSelect = (optionValue: string) => {
        if (multiple) {
            const currentValues = Array.isArray(value) ? value : [];
            // Handle "All" selection (empty value usually means reset)
            if (optionValue === "") {
                onChange([]); // or [""] if backend expects that, but empty usually means all
            } else {
                if (currentValues.includes(optionValue)) {
                    onChange(currentValues.filter(v => v !== optionValue));
                } else {
                    onChange([...currentValues, optionValue]);
                }
            }
            // Don't close on selection for multi-select
        } else {
            onChange(optionValue);
            setIsOpen(false);
        }
    };

    const isSelected = (optionValue: string) => {
        if (multiple && Array.isArray(value)) {
            return value.includes(optionValue);
        }
        return value === optionValue;
    };

    return (
        <div className="relative" ref={containerRef}>
            <div
                className={`
                    w-full bg-black/20 border border-white/5 rounded-lg py-2 pl-9 pr-3 text-sm text-white 
                    cursor-pointer flex items-center justify-between hover:bg-black/30 transition-colors
                    ${isOpen ? 'border-blue-500/50 ring-1 ring-blue-500/20' : ''}
                `}
                onClick={() => setIsOpen(!isOpen)}
            >
                {icon && <div className="absolute left-3 top-1/2 -translate-y-1/2 text-white/20">{icon}</div>}
                <span className={(multiple ? (Array.isArray(value) && value.length > 0) : value) ? 'text-white' : 'text-white/40'}>
                    {getDisplayLabel()}
                </span>
                <ChevronDown className={`w-4 h-4 text-white/40 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
            </div>

            {isOpen && (
                <div className="absolute top-full left-0 right-0 mt-1 bg-[#1e1e1e] border border-white/10 rounded-lg shadow-xl z-50 overflow-hidden animate-[fadeIn_0.1s_ease-out]">
                    <div className="max-h-60 overflow-y-auto custom-scrollbar p-1">
                        {options.map((option) => {
                            const selected = isSelected(option.value);
                            return (
                                <div
                                    key={option.value}
                                    onClick={() => handleSelect(option.value)}
                                    className={`
                                        px-3 py-2 rounded-md text-sm cursor-pointer flex items-center justify-between
                                        ${selected ? 'bg-blue-500/10 text-blue-400' : 'text-white/70 hover:bg-white/5 hover:text-white'}
                                    `}
                                >
                                    {option.label}
                                    {selected && <Check className="w-3 h-3" />}
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
};

interface CustomDatePickerProps {
    value: string;
    onChange: (date: string) => void;
    placeholder?: string;
}

export const CustomDatePicker = ({ value, onChange, placeholder = "DD.MM.YYYY" }: CustomDatePickerProps) => {
    const [isOpen, setIsOpen] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);

    // Internal state for calendar navigation
    const [viewDate, setViewDate] = useState(new Date());

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Effect to sync viewDate with value if provided
    useEffect(() => {
        if (value && !isNaN(Date.parse(value))) {
            setViewDate(new Date(value));
        }
    }, [isOpen, value]); // Sync selected value when picker is opened or value changes

    const months = [
        "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
    ];

    const getDaysInMonth = (year: number, month: number) => {
        return new Date(year, month + 1, 0).getDate();
    };

    const getFirstDayOfMonth = (year: number, month: number) => {
        // 0 = Sunday, but we want 0 = Monday.
        // JS getDay(): 0=Sun, 1=Mon...
        // Adjusted: 0=Mon, 6=Sun
        const day = new Date(year, month, 1).getDay();
        return day === 0 ? 6 : day - 1;
    };

    const handleDateClick = (day: number) => {
        // Format YYYY-MM-DD
        const month = viewDate.getMonth() + 1;
        const year = viewDate.getFullYear();
        const formattedDate = `${year}-${month.toString().padStart(2, '0')}-${day.toString().padStart(2, '0')}`;
        onChange(formattedDate);
        setIsOpen(false);
    };

    const changeMonth = (delta: number) => {
        const newDate = new Date(viewDate);
        newDate.setMonth(viewDate.getMonth() + delta);
        setViewDate(newDate);
    };

    const renderDays = () => {
        const year = viewDate.getFullYear();
        const month = viewDate.getMonth();
        const daysInMonth = getDaysInMonth(year, month);
        const startDay = getFirstDayOfMonth(year, month);

        const slots = [];

        // Empty slots
        for (let i = 0; i < startDay; i++) {
            slots.push(<div key={`empty-${i}`} className="h-8"></div>);
        }

        // Days
        for (let day = 1; day <= daysInMonth; day++) {
            const dateStr = `${year}-${(month + 1).toString().padStart(2, '0')}-${day.toString().padStart(2, '0')}`;
            const isSelected = value === dateStr;
            const isToday = new Date().toISOString().split('T')[0] === dateStr;

            slots.push(
                <button
                    key={day}
                    onClick={() => handleDateClick(day)}
                    className={`
                        h-8 w-8 rounded-full flex items-center justify-center text-sm transition-colors mx-auto
                        ${isSelected ? 'bg-blue-500 text-white font-bold' :
                            isToday ? 'border border-blue-500/50 text-blue-400' :
                                'text-white/80 hover:bg-white/10'}
                    `}
                >
                    {day}
                </button>
            );
        }
        return slots;
    };

    return (
        <div className="relative" ref={containerRef}>
            <div
                className={`
                    bg-black/20 border border-white/5 rounded-lg py-2 pl-3 pr-3 text-sm flex items-center gap-2 cursor-pointer hover:bg-black/30 transition-colors
                     ${isOpen ? 'border-blue-500/50 ring-1 ring-blue-500/20' : ''}
                `}
                onClick={() => setIsOpen(!isOpen)}
            >
                <CalendarIcon className="w-4 h-4 text-white/40" />
                <span className={value ? 'text-white' : 'text-white/40'}>
                    {value ? new Date(value).toLocaleDateString() : placeholder}
                </span>
                {value && (
                    <div
                        className="ml-auto p-1 hover:bg-white/10 rounded-full"
                        onClick={(e) => {
                            e.stopPropagation();
                            onChange("");
                        }}
                    >
                        <X className="w-3 h-3 text-white/40 hover:text-white" />
                    </div>
                )}
            </div>

            {isOpen && (
                <div className="absolute top-full left-0 mt-2 bg-[#1e1e1e] border border-white/10 rounded-xl shadow-2xl z-50 p-4 min-w-[280px] animate-[fadeIn_0.1s_ease-out]">
                    {/* Header */}
                    <div className="flex items-center justify-between mb-4">
                        <button onClick={() => changeMonth(-1)} className="p-1 hover:bg-white/10 rounded text-white/60 hover:text-white">
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <span className="font-bold text-white">
                            {months[viewDate.getMonth()]} {viewDate.getFullYear()}
                        </span>
                        <button onClick={() => changeMonth(1)} className="p-1 hover:bg-white/10 rounded text-white/60 hover:text-white">
                            <ChevronRight className="w-4 h-4" />
                        </button>
                    </div>

                    {/* Weekdays */}
                    <div className="grid grid-cols-7 mb-2">
                        {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map(d => (
                            <div key={d} className="text-center text-xs font-medium text-white/30 py-1">
                                {d}
                            </div>
                        ))}
                    </div>

                    {/* Days Grid */}
                    <div className="grid grid-cols-7 gap-y-1">
                        {renderDays()}
                    </div>

                    {/* Footer */}
                    <div className="mt-4 pt-3 border-t border-white/5 flex justify-between">
                        <button
                            onClick={() => {
                                onChange("");
                                setIsOpen(false);
                            }}
                            className="text-xs text-white/40 hover:text-white transition-colors"
                        >
                            Очистить
                        </button>
                        <button
                            onClick={() => {
                                const today = new Date();
                                const dateStr = today.toISOString().split('T')[0];
                                onChange(dateStr);
                                setIsOpen(false);
                            }}
                            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                        >
                            Сегодня
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
};

interface CustomTimePickerProps {
    value: string;
    onChange: (time: string) => void;
    placeholder?: string;
}

export const CustomTimePicker = ({ value, onChange, placeholder = "--:--" }: CustomTimePickerProps) => {
    const [isOpen, setIsOpen] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const hours = Array.from({ length: 24 }, (_, i) => i.toString().padStart(2, '0'));
    const minutes = Array.from({ length: 60 }, (_, i) => i.toString().padStart(2, '0'));

    const [selectedHour, selectedMinute] = value ? value.split(':') : ['', ''];

    const handleTimeSelect = (type: 'hour' | 'minute', val: string) => {
        let newHour = selectedHour;
        let newMinute = selectedMinute;

        if (type === 'hour') {
            newHour = val;
            if (!newMinute) newMinute = '00';
        } else {
            newMinute = val;
            if (!newHour) newHour = '00';
        }
        onChange(`${newHour}:${newMinute}`);
    };

    return (
        <div className="relative" ref={containerRef}>
            <div
                className={`
                    w-full bg-black/20 border border-white/5 rounded-xl p-3 text-white flex items-center justify-between cursor-pointer hover:bg-black/30 transition-colors
                    ${isOpen ? 'border-purple-500/50 ring-1 ring-purple-500/20' : ''}
                `}
                onClick={() => setIsOpen(!isOpen)}
            >
                <span className={value ? 'text-white' : 'text-white/40'}>
                    {value || placeholder}
                </span>
                <Clock className="w-4 h-4 text-white/40" />
            </div>

            {isOpen && (
                <div className="absolute top-full left-0 mt-2 bg-[#1e1e1e] border border-white/10 rounded-xl shadow-2xl z-50 p-2 min-w-[200px] flex gap-2 h-64 animate-[fadeIn_0.1s_ease-out]">
                    {/* Hours */}
                    <div className="flex-1 overflow-y-auto custom-scrollbar">
                        <div className="text-xs font-bold text-center text-white/40 mb-2 sticky top-0 bg-[#1e1e1e] py-1">Часы</div>
                        <div className="space-y-1">
                            {hours.map(h => (
                                <div
                                    key={h}
                                    onClick={() => handleTimeSelect('hour', h)}
                                    className={`text-center py-1 rounded cursor-pointer text-sm ${selectedHour === h ? 'bg-purple-500 text-white' : 'text-white/60 hover:bg-white/10'}`}
                                >
                                    {h}
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="w-[1px] bg-white/10 my-2"></div>

                    {/* Minutes */}
                    <div className="flex-1 overflow-y-auto custom-scrollbar">
                        <div className="text-xs font-bold text-center text-white/40 mb-2 sticky top-0 bg-[#1e1e1e] py-1">Мин</div>
                        <div className="space-y-1">
                            {minutes.map(m => (
                                <div
                                    key={m}
                                    onClick={() => handleTimeSelect('minute', m)}
                                    className={`text-center py-1 rounded cursor-pointer text-sm ${selectedMinute === m ? 'bg-purple-500 text-white' : 'text-white/60 hover:bg-white/10'}`}
                                >
                                    {m}
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};
