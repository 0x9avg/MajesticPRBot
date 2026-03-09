import React, { useState, useEffect, useRef } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, X, Calendar as CalendarIcon, Check, Clock, Search } from 'lucide-react';
import { getMskTodayStr, getMskNow, formatMskToLocal } from '../utils/datetime';

const dateOnlyFormatOptions: Intl.DateTimeFormatOptions = {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
};

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
    const [search, setSearch] = useState('');
    const containerRef = useRef<HTMLDivElement>(null);
    const searchRef = useRef<HTMLInputElement>(null);
    const closeMenu = () => {
        setIsOpen(false);
        setSearch('');
    };

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                closeMenu();
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Autofocus search when opens
    useEffect(() => {
        if (!isOpen) return undefined;

        const timeoutId = window.setTimeout(() => searchRef.current?.focus(), 50);
        return () => window.clearTimeout(timeoutId);
    }, [isOpen]);

    const filteredOptions = search.trim()
        ? options.filter(o => o.label.toLowerCase().includes(search.toLowerCase()))
        : options;

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
            if (optionValue === "") {
                onChange([]);
            } else {
                if (currentValues.includes(optionValue)) {
                    onChange(currentValues.filter(v => v !== optionValue));
                } else {
                    onChange([...currentValues, optionValue]);
                }
            }
        } else {
            onChange(optionValue);
            closeMenu();
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
                    w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2 pl-3 pr-3 text-sm text-white 
                    cursor-pointer flex items-center justify-between hover:border-white/20 hover:bg-[#323232] transition-colors
                    ${isOpen ? 'border-purple-500/50 ring-1 ring-purple-500/20' : ''}
                `}
                onClick={() => {
                    if (isOpen) {
                        closeMenu();
                    } else {
                        setIsOpen(true);
                    }
                }}
            >
                {icon && <div className="absolute left-3 top-1/2 -translate-y-1/2 text-white/20">{icon}</div>}
                <span className={`block truncate ${multiple && Array.isArray(value) && value.length === 0 ? 'text-white/40' : !value ? 'text-white/40' : 'text-white'} ${icon ? 'ml-6' : ''}`}>
                    {getDisplayLabel()}
                </span>
                <ChevronDown className={`w-4 h-4 text-white/40 transition-transform ${isOpen ? 'rotate-180' : ''} shrink-0 ml-2`} />
            </div>

            {isOpen && (
                <div className="absolute top-full left-0 right-0 mt-2 bg-[#1e1e1e] border border-white/10 rounded-xl shadow-[0_0_30px_rgba(0,0,0,0.5)] z-50 overflow-hidden animate-[fadeIn_0.1s_ease-out]">
                    {/* Search input */}
                    <div className="p-2 border-b border-white/5">
                        <div className="flex items-center gap-2 bg-[#2a2a2a] rounded-lg px-3 py-1.5">
                            <Search className="w-3.5 h-3.5 text-white/30 shrink-0" />
                            <input
                                ref={searchRef}
                                type="text"
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                onClick={(e) => e.stopPropagation()}
                                placeholder="Поиск..."
                                className="flex-1 bg-transparent text-sm text-white placeholder:text-white/30 outline-none"
                            />
                            {search && (
                                <button onClick={(e) => { e.stopPropagation(); setSearch(''); }} className="text-white/30 hover:text-white/70 transition-colors">
                                    <X className="w-3 h-3" />
                                </button>
                            )}
                        </div>
                    </div>
                    <div className="max-h-52 overflow-y-auto custom-scrollbar p-1.5 space-y-0.5">
                        {filteredOptions.length === 0 ? (
                            <div className="px-3 py-4 text-center text-sm text-white/30">Ничего не найдено</div>
                        ) : filteredOptions.map((option) => {
                            const selected = isSelected(option.value);
                            return (
                                <div
                                    key={option.value}
                                    onClick={() => handleSelect(option.value)}
                                    className={`
                                        px-3 py-2 rounded-lg text-sm cursor-pointer flex items-center justify-between transition-colors
                                        ${selected
                                            ? 'bg-purple-500/10 text-purple-300'
                                            : 'text-white/70 hover:bg-white/5 hover:text-white'}
                                    `}
                                >
                                    <span className="truncate">{option.label}</span>
                                    {selected && <Check className="w-4 h-4 shrink-0 ml-2" />}
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
};

// ==========================================
// Custom Dropdown (Premium Select) Component
// ==========================================
export interface DropdownOption {
    value: string;
    label: string | React.ReactNode;
    colorClass?: string;
    searchMatchString?: string; // used for filtering if label is ReactNode
}

interface CustomDropdownProps {
    value: string;
    onChange: (value: string) => void;
    options: DropdownOption[];
    placeholder?: string;
    icon?: React.ReactNode;
    disabled?: boolean;
    className?: string;
}

export const CustomDropdown = ({ value, onChange, options, placeholder = "Выберите...", icon, disabled = false, className = '' }: CustomDropdownProps) => {
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

    const selectedOption = options.find(opt => opt.value === value);

    return (
        <div className={`relative ${className}`} ref={containerRef}>
            <div
                className={`
                    w-full bg-[#2a2a2a] border border-white/10 rounded-lg py-2 px-3 text-sm 
                    flex items-center justify-between transition-all
                    ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:border-white/30 hover:bg-[#323232]'}
                    ${isOpen ? 'border-purple-500/50 shadow-[0_0_15px_rgba(168,85,247,0.15)] bg-[#323232]' : ''}
                `}
                onClick={() => !disabled && setIsOpen(!isOpen)}
            >
                <div className="flex items-center gap-2 overflow-hidden">
                    {icon && <div className="text-white/40 shrink-0">{icon}</div>}
                    <div className={`truncate font-medium ${selectedOption ? (selectedOption.colorClass || 'text-white') : 'text-white/40 font-normal'}`}>
                        {selectedOption ? selectedOption.label : placeholder}
                    </div>
                </div>
                <ChevronDown className={`w-4 h-4 text-white/40 transition-transform duration-200 shrink-0 ml-2 ${isOpen ? 'rotate-180 text-purple-400' : ''}`} />
            </div>

            {isOpen && (
                <div className="absolute top-[calc(100%+8px)] left-0 right-0 bg-[#1e1e1e] border border-white/10 rounded-xl shadow-[0_10px_40px_rgba(0,0,0,0.5)] z-50 overflow-hidden animate-[fadeIn_0.15s_ease-out] transform origin-top">
                    <div className="max-h-[280px] overflow-y-auto custom-scrollbar p-1.5 space-y-0.5">
                        {options.map((option) => {
                            const isSelected = value === option.value;
                            return (
                                <div
                                    key={option.value}
                                    onClick={() => {
                                        onChange(option.value);
                                        setIsOpen(false);
                                    }}
                                    className={`
                                        px-3 py-2.5 rounded-lg text-sm cursor-pointer flex items-center justify-between transition-all
                                        ${isSelected
                                            ? 'bg-purple-500/10 border border-purple-500/20'
                                            : 'border border-transparent hover:bg-white/5 hover:border-white/10'}
                                    `}
                                >
                                    <div className={`font-medium ${option.colorClass || (isSelected ? 'text-purple-300' : 'text-white/80')}`}>
                                        {option.label}
                                    </div>
                                    {isSelected && <Check className={`w-4 h-4 shrink-0 ml-2 ${option.colorClass || 'text-purple-400'}`} />}
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
    const [viewDate, setViewDate] = useState(getMskNow());

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
            const isToday = getMskTodayStr() === dateStr;

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
                    w-full bg-black/20 border border-white/5 rounded-xl p-3 text-white flex items-center justify-between cursor-pointer hover:bg-black/30 transition-colors
                    ${isOpen ? 'border-blue-500/50 ring-1 ring-blue-500/20' : ''}
                `}
                onClick={() => setIsOpen(!isOpen)}
            >
                <div className="flex items-center gap-2 overflow-hidden">
                    <CalendarIcon className="w-4 h-4 text-white/40 shrink-0" />
                    <span className={value ? 'text-white' : 'text-white/40'}>
                        {value ? formatMskToLocal(value, dateOnlyFormatOptions) : placeholder}
                    </span>
                </div>
                {value ? (
                    <div
                        className="p-1 hover:bg-white/10 rounded-full shrink-0"
                        onClick={(e) => {
                            e.stopPropagation();
                            onChange("");
                        }}
                    >
                        <X className="w-3 h-3 text-white/40 hover:text-white" />
                    </div>
                ) : (
                    <CalendarIcon className="w-4 h-4 text-white/40 shrink-0" />
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
                                const dateStr = getMskTodayStr();
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
