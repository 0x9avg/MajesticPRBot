import React from 'react';
import { useOutletContext } from 'react-router-dom';
import { FileText, Search, Filter, Eye, ChevronLeft, ChevronRight, LogIn, LogOut, Clock, User } from 'lucide-react';
import { CustomSelect, CustomDatePicker } from '../../components/CustomInputs';
import DetailsModal from './components/DetailsModal';
import NotificationToast from './components/NotificationToast';
import type { OutletUserContext } from '../../types/auth';
import type { AdminLogRecord } from '../../types/domain';
import { unwrapApiData } from '../../types/api';
import { formatMskToLocal } from '../../utils/datetime';

export type SpecSessionEndReason = 'manual_unclaim' | 'stream_end' | 'category_change' | 'admin_closed' | 'event_end' | 'event_rejected' | 'unknown';

interface PRActionLogItem {
    session_id: number;
    pr_id: string;
    pr_nickname: string | null;
    pr_role: string | null;
    target_type: string;
    target_id: string;
    target_name: string | null;
    target_avatar: string | null;
    target_is_online: boolean | null;
    action_time: string;
    action_type: 'join' | 'leave';
    duration_seconds: number | null;
    priority: number;
    is_probation: boolean;
    end_reason: SpecSessionEndReason | null;
}

interface AssistantOption {
    pr_id: string;
    nickname: string;
}

function formatDuration(seconds: number | null): string {
    if (!seconds || seconds <= 0) return '0с';
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    const parts: string[] = [];
    if (hours > 0) parts.push(`${hours}ч`);
    if (mins > 0) parts.push(`${mins}м`);
    if (secs > 0 && hours === 0) parts.push(`${secs}с`);
    return parts.join(' ') || '0с';
}

function priorityLabel(p: number): string {
    return `P${p}`;
}

function priorityColor(p: number): string {
    switch (p) {
        case 0: return 'bg-emerald-500/20 text-emerald-300 border border-emerald-400/30';
        case 1: return 'bg-yellow-500/20 text-yellow-300 border border-yellow-400/30';
        case 2: return 'bg-orange-500/20 text-orange-300 border border-orange-400/30';
        case 3: return 'bg-red-500/20 text-red-300 border border-red-400/30';
        default: return 'bg-white/10 text-white/60 border border-white/10';
    }
}

function roleBadge(role: string | null): { label: string; color: string } {
    switch (role) {
        case 'junior_employee': return { label: 'Стажер', color: 'bg-amber-500/20 text-amber-300' };
        case 'employee': return { label: 'Сотрудник', color: 'bg-sky-500/20 text-sky-300' };
        case 'senior_employee': return { label: 'Старший', color: 'bg-violet-500/20 text-violet-300' };
        case 'manager': return { label: 'Менеджер', color: 'bg-rose-500/20 text-rose-300' };
        case 'developer': return { label: 'Разработчик', color: 'bg-emerald-500/20 text-emerald-300' };
        default: return { label: role || '—', color: 'bg-white/10 text-white/50' };
    }
}

function endReasonLabel(reason: string | null): string {
    switch (reason) {
        case 'stream_end': return 'Стрим завершен';
        case 'category_change': return 'Смена категории';
        case 'manual_unclaim': return 'Открепился вручную';
        case 'admin_closed': return 'Завершено администратором';
        case 'event_end': return 'Событие завершено';
        case 'event_rejected': return 'Событие отклонено';
        case 'unknown': return 'Неизвестно';
        default: return 'Откреплен';
    }
}

export function SpectateLogs() {
    const { user } = useOutletContext<OutletUserContext>();
    const [activeTab, setActiveTab] = React.useState<'assistants' | 'admins'>('assistants');

    // ===== PR Action Logs State =====
    const [prLogs, setPrLogs] = React.useState<PRActionLogItem[]>([]);
    const [prLogsLoading, setPrLogsLoading] = React.useState(false);
    const [prLogsPage, setPrLogsPage] = React.useState(1);
    const [prLogsTotalPages, setPrLogsTotalPages] = React.useState(1);
    const [prLogsTotal, setPrLogsTotal] = React.useState(0);

    // Assistants list for filter
    const [assistantsList, setAssistantsList] = React.useState<AssistantOption[]>([]);

    // PR Logs Filters
    const [prFilters, setPrFilters] = React.useState({
        pr_id: '',
        priority: '',
        action_type: '',
        date_from: '',
        date_to: '',
    });

    // ===== Admin Logs State =====
    const [adminLogs, setAdminLogs] = React.useState<AdminLogRecord[]>([]);
    const [adminLoading, setAdminLoading] = React.useState(false);
    const [adminPage, setAdminPage] = React.useState(1);
    const [adminTotalPages, setAdminTotalPages] = React.useState(1);
    const [adminTotal, setAdminTotal] = React.useState(0);

    // Sort State
    const [sortConfig, setSortConfig] = React.useState({
        key: 'created_at',
        direction: 'desc' as 'asc' | 'desc'
    });

    // Filters State
    const [filters, setFilters] = React.useState({
        action: [] as string[],
        adminName: '',
        kind: '',
        targetType: '',
        startDate: '',
        endDate: ''
    });

    // Details Modal State
    const [selectedLog, setSelectedLog] = React.useState<AdminLogRecord | null>(null);

    const [notification, setNotification] = React.useState<string | null>(null);

    // Initial check
    const canViewAdminLogs = user?.permissions?.can_view_admin_logs === true ||
        user?.role === 'manager' ||
        user?.role === 'developer';

    // ==================== PR Action Logs Logic ====================

    // Load assistants list for filter dropdown
    React.useEffect(() => {
        const loadAssistants = async () => {
            try {
                const token = localStorage.getItem('access_token');
                const res = await fetch('/api/assistants', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (res.ok) {
                    const json = await res.json() as unknown;
                    const data = unwrapApiData<AssistantOption[]>(json);
                    if (Array.isArray(data)) {
                        setAssistantsList(data.map(a => ({
                            pr_id: String(a.pr_id),
                            nickname: a.nickname || String(a.pr_id)
                        })));
                    }
                }
            } catch (e) {
                console.error('Failed to load assistants list:', e);
            }
        };
        void loadAssistants();
    }, []);

    const fetchPrLogs = React.useCallback(async (page: number) => {
        setPrLogsLoading(true);
        try {
            const token = localStorage.getItem('access_token');
            const params = new URLSearchParams();
            params.append('page', page.toString());
            params.append('limit', '20');

            if (prFilters.pr_id) params.append('pr_id', prFilters.pr_id);
            if (prFilters.priority) params.append('priority', prFilters.priority);
            if (prFilters.action_type) params.append('action_type', prFilters.action_type);
            if (prFilters.date_from) params.append('date_from', prFilters.date_from);
            if (prFilters.date_to) params.append('date_to', prFilters.date_to);

            const res = await fetch(`/api/logs/pr-actions?${params.toString()}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (res.ok) {
                const json = await res.json() as unknown;
                const data = unwrapApiData<{
                    items: PRActionLogItem[];
                    total: number;
                    page: number;
                    pages: number;
                }>(json);

                setPrLogs(data.items || []);
                setPrLogsTotal(data.total || 0);
                setPrLogsPage(data.page || 1);
                setPrLogsTotalPages(data.pages || 1);
            }
        } catch (e) {
            console.error('Failed to fetch PR action logs:', e);
        } finally {
            setPrLogsLoading(false);
        }
    }, [prFilters]);

    React.useEffect(() => {
        if (activeTab === 'assistants') {
            void fetchPrLogs(1);
        }
    }, [activeTab, fetchPrLogs]);

    const handlePrApplyFilters = () => {
        setPrLogsPage(1);
        void fetchPrLogs(1);
    };

    const handlePrResetFilters = () => {
        setPrFilters({ pr_id: '', priority: '', action_type: '', date_from: '', date_to: '' });
        setPrLogsPage(1);
    };

    React.useEffect(() => {
        if (activeTab === 'assistants' && !prFilters.pr_id && !prFilters.priority && !prFilters.action_type && !prFilters.date_from && !prFilters.date_to) {
            void fetchPrLogs(1);
        }
    }, [activeTab, prFilters, fetchPrLogs]);

    const handlePrPageChange = (newPage: number) => {
        if (newPage < 1 || newPage > prLogsTotalPages) return;
        setPrLogsPage(newPage);
        void fetchPrLogs(newPage);
    };

    // Build page numbers for pagination
    const getPageNumbers = (totalPages: number, currentPage: number) => {
        const pages: (number | '...')[] = [];

        if (totalPages <= 7) {
            for (let i = 1; i <= totalPages; i++) pages.push(i);
        } else {
            pages.push(1);
            if (currentPage > 3) pages.push('...');
            for (let i = Math.max(2, currentPage - 1); i <= Math.min(totalPages - 1, currentPage + 1); i++) {
                pages.push(i);
            }
            if (currentPage < totalPages - 2) pages.push('...');
            pages.push(totalPages);
        }
        return pages;
    };

    // Filter options
    const assistantOptions = [
        { value: '', label: 'Все ассистенты' },
        ...assistantsList.map(a => ({ value: a.pr_id, label: a.nickname }))
    ];

    const priorityOptions = [
        { value: '', label: 'Все приоритеты' },
        { value: '0', label: 'P0 (Низкий)' },
        { value: '1', label: 'P1 (Обычный)' },
        { value: '2', label: 'P2 (Важный)' },
        { value: '3', label: 'P3 (Критический)' },
    ];

    const actionTypeOptions = [
        { value: '', label: 'Все действия' },
        { value: 'join', label: '📥 Закрепления' },
        { value: 'leave', label: '📤 Открепления' },
    ];

    // ==================== Admin Logs Logic ====================
    const resolveKind = React.useCallback((action: string): string => {
        if (!action || !action.includes('.')) return 'other';
        return action.split('.', 1)[0];
    }, []);

    const kindBadgeClass = React.useCallback((kind: string): string => {
        switch (kind) {
            case 'user':
                return 'bg-sky-500/20 text-sky-300 border border-sky-400/30';
            case 'streamer':
                return 'bg-emerald-500/20 text-emerald-300 border border-emerald-400/30';
            case 'event':
                return 'bg-amber-500/20 text-amber-300 border border-amber-400/30';
            case 'assistant':
                return 'bg-fuchsia-500/20 text-fuchsia-300 border border-fuchsia-400/30';
            case 'system':
                return 'bg-rose-500/20 text-rose-300 border border-rose-400/30';
            case 'rbac':
                return 'bg-indigo-500/20 text-indigo-300 border border-indigo-400/30';
            case 'spec':
                return 'bg-cyan-500/20 text-cyan-300 border border-cyan-400/30';
            case 'guild':
                return 'bg-lime-500/20 text-lime-300 border border-lime-400/30';
            default:
                return 'bg-white/10 text-white/70 border border-white/10';
        }
    }, []);

    const fetchAdminLogs = React.useCallback(async (page: number) => {
        setAdminLoading(true);
        try {
            const token = localStorage.getItem('access_token');
            const params = new URLSearchParams();
            params.append('page', page.toString());
            params.append('limit', '20');
            params.append('sort_by', sortConfig.key);
            params.append('sort_order', sortConfig.direction);

            if (filters.action && filters.action.length > 0) {
                filters.action.forEach(act => params.append('action', act));
            }
            if (filters.adminName) params.append('actor_name', filters.adminName);
            if (filters.kind) params.append('kind', filters.kind);
            if (filters.targetType) params.append('target_type', filters.targetType);
            if (filters.startDate) params.append('start_date', filters.startDate);
            if (filters.endDate) params.append('end_date', filters.endDate);

            const response = await fetch(`/api/logs/admin?${params.toString()}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (response.ok) {
                const json = await response.json() as unknown;
                const data = unwrapApiData<{
                    items: AdminLogRecord[];
                    total: number;
                    page: number;
                    pages: number;
                }>(json);

                setAdminLogs(data.items || []);
                setAdminTotal(data.total || 0);
                setAdminPage(data.page || 1);
                setAdminTotalPages(data.pages || 1);
            }
        } catch (error) {
            console.error('Failed to fetch admin logs:', error);
        } finally {
            setAdminLoading(false);
        }
    }, [sortConfig, filters]);

    React.useEffect(() => {
        if (activeTab === 'admins' && canViewAdminLogs) {
            void fetchAdminLogs(1);
        }
    }, [activeTab, canViewAdminLogs, fetchAdminLogs]);

    const handleApplyFilters = () => {
        setAdminPage(1);
        void fetchAdminLogs(1);
    };

    const handleResetFilters = () => {
        setFilters({
            action: [],
            adminName: '',
            kind: '',
            targetType: '',
            startDate: '',
            endDate: ''
        });
        setSortConfig({
            key: 'created_at',
            direction: 'desc'
        });
    };

    const handleAdminPageChange = (newPage: number) => {
        if (newPage < 1 || newPage > adminTotalPages) return;
        setAdminPage(newPage);
        void fetchAdminLogs(newPage);
    };

    const handleCopyLog = (log: AdminLogRecord) => {
        const date = formatMskToLocal(log.created_at);
        const details = log.details ? JSON.stringify(log.details, null, 2) : 'Нет деталей';
        const actorName = log.actor_name || log.admin_name || 'unknown';
        const actorRole = log.actor_role || log.admin_role || 'unknown';

        const textToCopy = `[ ${date} ] [ ${actorName} | ${actorRole} ] [ ${log.action} ]\n\`\`\`md\n${details}\n\`\`\``;

        navigator.clipboard.writeText(textToCopy).then(() => {
            setNotification(`Вы успешно скопировали лог #${log.id}`);
            setTimeout(() => setNotification(null), 2000);
        });
    };

    const actionOptions = [
        { value: '', label: 'Все действия' },
        { value: 'user.create', label: 'user.create' },
        { value: 'streamer.add', label: 'streamer.add' },
        { value: 'event.create', label: 'event.create' },
        { value: 'event.update', label: 'event.update' },
        { value: 'assistant.spec_points.adjust.permanent', label: 'assistant.spec_points.adjust.permanent' },
        { value: 'assistant.spec_time.add', label: 'assistant.spec_time.add' },
        { value: 'assistant.spec_time.subtract', label: 'assistant.spec_time.subtract' },
        { value: 'system.maintenance.enable', label: 'system.maintenance.enable' },
        { value: 'system.maintenance.disable', label: 'system.maintenance.disable' },
        { value: 'rbac.matrix.update', label: 'rbac.matrix.update' },
    ];

    const kindOptions = [
        { value: '', label: 'Все категории' },
        { value: 'user', label: 'user.*' },
        { value: 'streamer', label: 'streamer.*' },
        { value: 'event', label: 'event.*' },
        { value: 'assistant', label: 'assistant.*' },
        { value: 'system', label: 'system.*' },
        { value: 'rbac', label: 'rbac.*' },
        { value: 'spec', label: 'spec.*' },
        { value: 'guild', label: 'guild.*' },
        { value: 'other', label: 'other' },
    ];

    const tabs = [
        { id: 'assistants' as const, label: 'Действия ассистентов' },
        ...(canViewAdminLogs ? [{ id: 'admins' as const, label: 'Действия администраторов' }] : [])
    ];

    return (
        <div className="space-y-6 animate-[fadeIn_0.5s_ease-in-out]">
            <h2 className="text-3xl font-bold flex items-center gap-2">
                <span className="w-1 h-8 bg-[#3b82f6] rounded-full inline-block"></span>
                Логи действий
            </h2>

            {/* Tabs */}
            <div className="flex gap-2 border-b border-white/10 pb-2">
                {tabs.map(tab => (
                    <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        className={`px-6 py-3 rounded-t-lg font-semibold transition-all relative ${activeTab === tab.id
                            ? 'bg-white/10 text-white border-b-2 border-blue-500'
                            : 'text-white/60 hover:text-white hover:bg-white/5'
                            }`}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {activeTab === 'assistants' && (
                <div className="space-y-4">
                    {/* Filters Bar for PR Actions */}
                    <div className="relative z-50 bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-4 flex flex-wrap gap-4 items-end">
                        <div className="flex-1 min-w-[200px]">
                            <label className="text-xs font-medium text-white/40 mb-1 block">Ассистент</label>
                            <CustomSelect
                                value={prFilters.pr_id}
                                onChange={(val) => {
                                    if (typeof val === 'string') {
                                        setPrFilters(prev => ({ ...prev, pr_id: val }));
                                    }
                                }}
                                options={assistantOptions}
                                icon={<User className="w-4 h-4" />}
                                placeholder="Выберите ассистента"
                            />
                        </div>

                        <div className="flex-1 min-w-[180px]">
                            <label className="text-xs font-medium text-white/40 mb-1 block">Приоритет</label>
                            <CustomSelect
                                value={prFilters.priority}
                                onChange={(val) => {
                                    if (typeof val === 'string') {
                                        setPrFilters(prev => ({ ...prev, priority: val }));
                                    }
                                }}
                                options={priorityOptions}
                                icon={<Filter className="w-4 h-4" />}
                                placeholder="Все приоритеты"
                            />
                        </div>

                        <div className="flex-1 min-w-[180px]">
                            <label className="text-xs font-medium text-white/40 mb-1 block">Тип действия</label>
                            <CustomSelect
                                value={prFilters.action_type}
                                onChange={(val) => {
                                    if (typeof val === 'string') {
                                        setPrFilters(prev => ({ ...prev, action_type: val }));
                                    }
                                }}
                                options={actionTypeOptions}
                                icon={<Filter className="w-4 h-4" />}
                                placeholder="Все действия"
                            />
                        </div>

                        <div className="flex gap-2">
                            <div>
                                <label className="text-xs font-medium text-white/40 mb-1 block">С даты</label>
                                <CustomDatePicker
                                    value={prFilters.date_from}
                                    onChange={(val) => setPrFilters(prev => ({ ...prev, date_from: val }))}
                                    placeholder="ДД.ММ.ГГГГ"
                                />
                            </div>
                            <div>
                                <label className="text-xs font-medium text-white/40 mb-1 block">По дату</label>
                                <CustomDatePicker
                                    value={prFilters.date_to}
                                    onChange={(val) => setPrFilters(prev => ({ ...prev, date_to: val }))}
                                    placeholder="ДД.ММ.ГГГГ"
                                />
                            </div>
                        </div>

                        <div className="flex gap-2">
                            <button
                                onClick={handlePrApplyFilters}
                                className="px-4 py-2 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 border border-blue-500/20 rounded-lg text-sm font-medium transition-colors"
                            >
                                Применить
                            </button>
                            <button
                                onClick={handlePrResetFilters}
                                className="px-4 py-2 bg-white/5 hover:bg-white/10 text-white/60 hover:text-white border border-white/5 rounded-lg text-sm font-medium transition-colors"
                            >
                                Сброс
                            </button>
                        </div>
                    </div>

                    {/* Stats bar */}
                    <div className="flex items-center justify-between text-sm text-white/40 px-1">
                        <span>Всего записей: <span className="text-white/80 font-semibold">{prLogsTotal}</span></span>
                        <span>Страница {prLogsPage} из {prLogsTotalPages}</span>
                    </div>

                    {/* PR Action Logs Timeline */}
                    <div className="space-y-3">
                        {prLogsLoading ? (
                            <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-12 text-center">
                                <div className="animate-pulse flex flex-col items-center gap-3">
                                    <div className="w-12 h-12 rounded-full bg-white/5" />
                                    <div className="h-4 w-32 bg-white/5 rounded" />
                                    <span className="text-white/30 text-sm">Загрузка логов...</span>
                                </div>
                            </div>
                        ) : prLogs.length > 0 ? (
                            prLogs.map((log, index) => {
                                const isJoin = log.action_type === 'join';
                                const isEvent = log.target_type === 'event';
                                const role = roleBadge(log.pr_role);

                                // Border color based on action
                                const borderColor = isJoin
                                    ? (isEvent ? 'border-l-purple-500' : 'border-l-emerald-500')
                                    : (log.end_reason === 'stream_end' ? 'border-l-slate-500'
                                        : log.end_reason === 'category_change' ? 'border-l-orange-500'
                                            : 'border-l-red-500');

                                // Icon bg color
                                const iconBg = isJoin
                                    ? (isEvent ? 'bg-purple-500' : 'bg-emerald-500')
                                    : 'bg-red-500/80';

                                return (
                                    <div
                                        key={`${log.session_id}-${log.action_type}-${index}`}
                                        className={`group bg-[#242424]/60 backdrop-blur-sm border border-white/5 rounded-xl border-l-4 ${borderColor} overflow-hidden transition-all hover:bg-[#2a2a2a]/80 hover:border-white/10 hover:shadow-lg hover:shadow-black/20`}
                                    >
                                        <div className="flex items-stretch">
                                            {/* Left: Avatar section */}
                                            <div className="flex items-center px-4 py-4">
                                                <div className="relative flex-shrink-0">
                                                    {log.target_avatar ? (
                                                        <img
                                                            src={log.target_avatar}
                                                            alt={log.target_name || ''}
                                                            className="w-12 h-12 rounded-full object-cover ring-2 ring-white/10 group-hover:ring-white/20 transition-all"
                                                        />
                                                    ) : (
                                                        <div className="w-12 h-12 rounded-full bg-gradient-to-br from-white/10 to-white/5 flex items-center justify-center ring-2 ring-white/10">
                                                            <span className="text-lg font-bold text-white/30">
                                                                {isEvent ? '🎉' : (log.target_name?.[0]?.toUpperCase() || '?')}
                                                            </span>
                                                        </div>
                                                    )}
                                                    {/* Online indicator */}
                                                    {!!log.target_is_online && (
                                                        <div className="absolute -bottom-0.5 -right-0.5 w-4 h-4 rounded-full bg-red-500 border-2 border-[#242424] flex items-center justify-center">
                                                            <div className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                                                        </div>
                                                    )}
                                                    {/* Action icon overlay */}
                                                    <div className={`absolute -top-1 -left-1 w-5 h-5 rounded-full ${iconBg} flex items-center justify-center shadow-md`}>
                                                        {isJoin
                                                            ? <LogIn className="w-2.5 h-2.5 text-white" />
                                                            : <LogOut className="w-2.5 h-2.5 text-white" />
                                                        }
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Center: Info */}
                                            <div className="flex-1 py-3 pr-4 min-w-0">
                                                {/* Row 1: Target name + badges */}
                                                <div className="flex items-center gap-2 flex-wrap mb-1">
                                                    <span className="font-bold text-white text-sm truncate">
                                                        {log.target_name || `${log.target_type} #${log.target_id}`}
                                                    </span>
                                                    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${priorityColor(log.priority)}`}>
                                                        {priorityLabel(log.priority)}
                                                    </span>
                                                    {isEvent && (
                                                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-400/30">
                                                            Событие
                                                        </span>
                                                    )}
                                                    {!!log.target_is_online && !isEvent && (
                                                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-400/30 flex items-center gap-1">
                                                            <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
                                                            LIVE
                                                        </span>
                                                    )}
                                                </div>

                                                {/* Row 2: Action description */}
                                                <div className="flex items-center gap-1.5 text-sm text-white/60 mb-1.5">
                                                    <span className={isJoin ? 'text-emerald-400' : 'text-red-400'}>
                                                        {isJoin ? '📥' : '📤'}
                                                    </span>
                                                    <span>
                                                        {isJoin ? 'Закреплен' : endReasonLabel(log.end_reason)}
                                                    </span>
                                                    <span className="text-white/20">•</span>
                                                    <span className="font-medium text-white/80">{log.pr_nickname || `PR #${log.pr_id}`}</span>
                                                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${role.color}`}>{role.label}</span>
                                                </div>

                                                {/* Row 3: Meta chips */}
                                                <div className="flex items-center gap-2 flex-wrap">
                                                    {!!log.is_probation && (
                                                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-400/20">
                                                            Испытательный
                                                        </span>
                                                    )}
                                                    {!isJoin && log.duration_seconds != null && (
                                                        <span className="flex items-center gap-1 text-[11px] text-white/50">
                                                            <Clock className="w-3 h-3" />
                                                            {formatDuration(log.duration_seconds)}
                                                        </span>
                                                    )}
                                                </div>
                                            </div>

                                            {/* Right: Timestamp */}
                                            <div className="flex flex-col items-end justify-center pr-4 py-3 flex-shrink-0">
                                                <span className="text-xs text-white/35 tabular-nums">
                                                    {formatMskToLocal(log.action_time, { day: '2-digit', month: 'short' })}
                                                </span>
                                                <span className="text-[11px] text-white/25 tabular-nums">
                                                    {formatMskToLocal(log.action_time, { hour: '2-digit', minute: '2-digit' })}
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                );
                            })
                        ) : (
                            <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-12 text-center">
                                <div className="w-16 h-16 rounded-full bg-white/5 flex items-center justify-center mx-auto mb-4">
                                    <FileText className="w-8 h-8 text-white/15" />
                                </div>
                                <h3 className="text-lg font-bold text-white/70 mb-1">Нет записей</h3>
                                <p className="text-sm text-white/30">Попробуйте изменить фильтры</p>
                            </div>
                        )}
                    </div>

                    {/* Pagination for PR Actions */}
                    {prLogsTotalPages > 1 && (
                        <div className="flex justify-center items-center gap-2 mt-6">
                            <button
                                onClick={() => handlePrPageChange(prLogsPage - 1)}
                                disabled={prLogsPage === 1 || prLogsLoading}
                                className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-white/60 hover:text-white disabled:opacity-50 transition-colors"
                            >
                                <ChevronLeft className="w-4 h-4" />
                            </button>
                            {getPageNumbers(prLogsTotalPages, prLogsPage).map((page, index) => (
                                <button
                                    key={index}
                                    onClick={() => typeof page === 'number' && handlePrPageChange(page)}
                                    disabled={page === '...' || prLogsLoading}
                                    className={`px-3 py-1 rounded-lg text-sm font-medium ${prLogsPage === page
                                        ? 'bg-blue-500 text-white'
                                        : 'bg-white/5 hover:bg-white/10 text-white/60 hover:text-white'
                                        } disabled:opacity-50 transition-colors`}
                                >
                                    {page}
                                </button>
                            ))}
                            <button
                                onClick={() => handlePrPageChange(prLogsPage + 1)}
                                disabled={prLogsPage === prLogsTotalPages || prLogsLoading}
                                className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-white/60 hover:text-white disabled:opacity-50 transition-colors"
                            >
                                <ChevronRight className="w-4 h-4" />
                            </button>
                        </div>
                    )}
                </div>
            )}
            {notification && <NotificationToast message={notification} />}
            {
                activeTab === 'admins' && canViewAdminLogs && (
                    <div className="space-y-4">
                        {/* Filters Bar */}
                        <div className="relative z-50 bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-4 flex flex-wrap gap-4 items-end">
                            <div className="flex-1 min-w-[200px]">
                                <label className="text-xs font-medium text-white/40 mb-1 block">Поиск по админу</label>
                                <div className="relative">
                                    <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-white/20" />
                                    <input
                                        type="text"
                                        placeholder="Имя администратора..."
                                        value={filters.adminName}
                                        onChange={(e) => setFilters(prev => ({ ...prev, adminName: e.target.value }))}
                                        className="w-full bg-black/20 border border-white/5 rounded-lg py-2 pl-9 pr-4 text-sm text-white focus:outline-none focus:border-blue-500/50 transition-colors"
                                    />
                                </div>
                            </div>

                            <div className="flex-1 min-w-[200px]">
                                <label className="text-xs font-medium text-white/40 mb-1 block">Действие</label>
                                <CustomSelect
                                    value={filters.action}
                                    onChange={(val) => {
                                        if (Array.isArray(val)) {
                                            setFilters(prev => ({ ...prev, action: val }));
                                        }
                                    }}
                                    options={actionOptions}
                                    icon={<Filter className="w-4 h-4" />}
                                    placeholder="Выберите действие"
                                    multiple={true}
                                />
                            </div>

                            <div className="flex-1 min-w-[180px]">
                                <label className="text-xs font-medium text-white/40 mb-1 block">Категория</label>
                                <CustomSelect
                                    value={filters.kind}
                                    onChange={(val) => {
                                        if (typeof val === 'string') {
                                            setFilters(prev => ({ ...prev, kind: val }));
                                        }
                                    }}
                                    options={kindOptions}
                                    icon={<Filter className="w-4 h-4" />}
                                    placeholder="Все категории"
                                />
                            </div>

                            <div className="flex gap-2">
                                <div>
                                    <label className="text-xs font-medium text-white/40 mb-1 block">С даты</label>
                                    <CustomDatePicker
                                        value={filters.startDate}
                                        onChange={(val) => setFilters(prev => ({ ...prev, startDate: val }))}
                                        placeholder="ДД.ММ.ГГГГ"
                                    />
                                </div>
                                <div>
                                    <label className="text-xs font-medium text-white/40 mb-1 block">По дату</label>
                                    <CustomDatePicker
                                        value={filters.endDate}
                                        onChange={(val) => setFilters(prev => ({ ...prev, endDate: val }))}
                                        placeholder="ДД.ММ.ГГГГ"
                                    />
                                </div>
                            </div>

                            <div className="flex gap-2">
                                <button
                                    onClick={handleApplyFilters}
                                    className="px-4 py-2 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 border border-blue-500/20 rounded-lg text-sm font-medium transition-colors"
                                >
                                    Применить
                                </button>
                                <button
                                    onClick={handleResetFilters}
                                    className="px-4 py-2 bg-white/5 hover:bg-white/10 text-white/60 hover:text-white border border-white/5 rounded-lg text-sm font-medium transition-colors"
                                >
                                    Сброс
                                </button>
                            </div>
                        </div>

                        {/* Stats bar */}
                        <div className="flex justify-between items-center bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-xl px-4 py-2">
                            <span className="text-xs text-white/40">Всего записей: <span className="text-white/70 font-medium">{adminTotal}</span></span>
                            <span className="text-xs text-white/40">Страница <span className="text-white/70 font-medium">{adminPage}</span> из <span className="text-white/70 font-medium">{adminTotalPages}</span></span>
                        </div>

                        {/* Admin Log Cards */}
                        <div className="space-y-2">
                            {adminLoading ? (
                                <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-12 text-center">
                                    <div className="animate-pulse flex flex-col items-center gap-3">
                                        <div className="w-12 h-12 rounded-full bg-white/5" />
                                        <div className="h-4 w-32 bg-white/5 rounded" />
                                        <span className="text-white/30 text-sm">Загрузка логов...</span>
                                    </div>
                                </div>
                            ) : adminLogs.length > 0 ? (
                                adminLogs.map((log) => {
                                    const kind = log.kind || resolveKind(log.action);
                                    return (
                                        <div
                                            key={log.id}
                                            className="group bg-[#242424]/60 backdrop-blur-sm border border-white/5 rounded-xl overflow-hidden transition-all hover:bg-[#2a2a2a]/80 hover:border-white/10 hover:shadow-lg hover:shadow-black/20 cursor-pointer"
                                            onDoubleClick={() => handleCopyLog(log)}
                                        >
                                            <div className="flex items-stretch">
                                                {/* Left: Kind indicator */}
                                                <div className="flex items-center px-4 py-3">
                                                    <span className={`text-[10px] font-bold px-2 py-1 rounded ${kindBadgeClass(kind)} uppercase tracking-wide`}>
                                                        {kind}
                                                    </span>
                                                </div>

                                                {/* Center: Info */}
                                                <div className="flex-1 py-3 pr-4 min-w-0">
                                                    {/* Row 1: Action */}
                                                    <div className="flex items-center gap-2 flex-wrap mb-1">
                                                        <span className="font-mono text-xs text-white/80 font-medium">{log.action}</span>
                                                    </div>

                                                    {/* Row 2: Actor + Target */}
                                                    <div className="flex items-center gap-1.5 text-sm text-white/60 mb-1">
                                                        <span className="font-medium text-white/80">{log.actor_name || log.admin_name || 'unknown'}</span>
                                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-white/40">
                                                            {log.actor_role || log.admin_role || 'unknown'}
                                                        </span>
                                                        {(log.target_name || log.target_id) && (
                                                            <>
                                                                <span className="text-white/20">→</span>
                                                                <span className="text-white/70">{log.target_name || log.target_id}</span>
                                                                {log.target_type && (
                                                                    <span className="text-[10px] px-1 py-0.5 rounded bg-white/5 text-white/30 font-mono">
                                                                        {log.target_type}
                                                                    </span>
                                                                )}
                                                            </>
                                                        )}
                                                    </div>

                                                    {/* Row 3: Summary */}
                                                    {log.details?.summary && (
                                                        <p className="text-xs text-white/50 truncate">{log.details.summary}</p>
                                                    )}
                                                </div>

                                                {/* Right: Timestamp + Details */}
                                                <div className="flex items-center gap-3 pr-4 py-3 flex-shrink-0">
                                                    <div className="flex flex-col items-end">
                                                        <span className="text-xs text-white/35 tabular-nums">
                                                            {formatMskToLocal(log.created_at, { day: '2-digit', month: 'short' })}
                                                        </span>
                                                        <span className="text-[11px] text-white/25 tabular-nums">
                                                            {formatMskToLocal(log.created_at, { hour: '2-digit', minute: '2-digit' })}
                                                        </span>
                                                    </div>
                                                    {log.details && (
                                                        <button
                                                            onClick={(e) => { e.stopPropagation(); setSelectedLog(log); }}
                                                            className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/5 transition-all"
                                                        >
                                                            <Eye className="w-3.5 h-3.5 text-white/40 hover:text-white" />
                                                        </button>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })
                            ) : (
                                <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-12 text-center">
                                    <div className="w-16 h-16 rounded-full bg-white/5 flex items-center justify-center mx-auto mb-4">
                                        <FileText className="w-8 h-8 text-white/15" />
                                    </div>
                                    <h3 className="text-lg font-bold text-white/70 mb-1">Нет записей</h3>
                                    <p className="text-sm text-white/30">Попробуйте изменить фильтры</p>
                                </div>
                            )}
                        </div>

                        {/* Pagination for Admin Logs */}
                        {adminTotalPages > 1 && (
                            <div className="flex justify-center items-center gap-2 mt-4">
                                <button
                                    onClick={() => handleAdminPageChange(adminPage - 1)}
                                    disabled={adminPage === 1 || adminLoading}
                                    className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-white/60 hover:text-white disabled:opacity-50 transition-colors"
                                >
                                    <ChevronLeft className="w-4 h-4" />
                                </button>
                                {getPageNumbers(adminTotalPages, adminPage).map((page, index) => (
                                    <button
                                        key={index}
                                        onClick={() => typeof page === 'number' && handleAdminPageChange(page)}
                                        disabled={page === '...' || adminLoading}
                                        className={`px-3 py-1 rounded-lg text-sm font-medium ${adminPage === page
                                            ? 'bg-blue-500 text-white'
                                            : 'bg-white/5 hover:bg-white/10 text-white/60 hover:text-white'
                                            } disabled:opacity-50 transition-colors`}
                                    >
                                        {page}
                                    </button>
                                ))}
                                <button
                                    onClick={() => handleAdminPageChange(adminPage + 1)}
                                    disabled={adminPage === adminTotalPages || adminLoading}
                                    className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-white/60 hover:text-white disabled:opacity-50 transition-colors"
                                >
                                    <ChevronRight className="w-4 h-4" />
                                </button>
                            </div>
                        )}
                        {notification && <NotificationToast message={notification} />}

                        <DetailsModal
                            isOpen={!!selectedLog}
                            onClose={() => setSelectedLog(null)}
                            data={selectedLog?.details}
                            title={`Детали лога #${selectedLog?.id}`}
                        />
                    </div>
                )
            }
        </div >
    );
}

export default SpectateLogs;
