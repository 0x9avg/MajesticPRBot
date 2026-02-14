import React from 'react';
import { useOutletContext } from 'react-router-dom';
import { FileText, Search, Filter, Eye, ArrowUp, ArrowDown } from 'lucide-react';
import { CustomSelect, CustomDatePicker } from '../../components/CustomInputs';
import DetailsModal from './components/DetailsModal';
import NotificationToast from './components/NotificationToast';
import type { OutletUserContext } from '../../types/auth';
import type { AdminLogRecord } from '../../types/domain';
import { unwrapApiData } from '../../types/api';

export function SpectateLogs() {
    const { user } = useOutletContext<OutletUserContext>();
    const [activeTab, setActiveTab] = React.useState<'assistants' | 'admins'>('assistants');    // Admin Logs State
    const [adminLogs, setAdminLogs] = React.useState<AdminLogRecord[]>([]);
    const [loading, setLoading] = React.useState(false);
    const [pageConfig, setPageConfig] = React.useState({
        limit: 20,
        offset: 0,
        hasMore: true
    });

    // Sort State
    const [sortConfig, setSortConfig] = React.useState({
        key: 'created_at',
        direction: 'desc' as 'asc' | 'desc'
    });

    // Filters State
    const [filters, setFilters] = React.useState({
        action: [] as string[],
        adminName: '',
        targetType: '',
        startDate: '',
        endDate: ''
    });

    // Details Modal State
    const [selectedLog, setSelectedLog] = React.useState<AdminLogRecord | null>(null);

    const [notification, setNotification] = React.useState<string | null>(null);
    const loadingRef = React.useRef(false);
    const pageConfigRef = React.useRef(pageConfig);
    const sortConfigRef = React.useRef(sortConfig);
    const filtersRef = React.useRef(filters);

    // Initial check
    const canViewAdminLogs = user?.permissions?.can_view_admin_logs === true ||
        user?.role === 'manager' ||
        user?.role === 'developer';

    React.useEffect(() => {
        pageConfigRef.current = pageConfig;
    }, [pageConfig]);

    React.useEffect(() => {
        sortConfigRef.current = sortConfig;
    }, [sortConfig]);

    React.useEffect(() => {
        filtersRef.current = filters;
    }, [filters]);

    const fetchAdminLogs = React.useCallback(async (isLoadMore = false) => {
        if (loadingRef.current) return;
        loadingRef.current = true;
        setLoading(true);
        try {
            const token = localStorage.getItem('access_token');
            const currentConfig = pageConfigRef.current;
            const currentSort = sortConfigRef.current;
            const currentFilters = filtersRef.current;
            const currentOffset = isLoadMore ? currentConfig.offset + currentConfig.limit : 0;

            // Build query params
            const params = new URLSearchParams();
            params.append('limit', currentConfig.limit.toString());
            params.append('offset', currentOffset.toString());
            params.append('sort_by', currentSort.key);
            params.append('sort_order', currentSort.direction);

            if (currentFilters.action && currentFilters.action.length > 0) {
                currentFilters.action.forEach(act => params.append('action', act));
            }
            if (currentFilters.adminName) params.append('admin_name', currentFilters.adminName);
            if (currentFilters.targetType) params.append('target_type', currentFilters.targetType);
            if (currentFilters.startDate) params.append('start_date', currentFilters.startDate);
            if (currentFilters.endDate) params.append('end_date', currentFilters.endDate);

            const response = await fetch(`/api/logs/admin?${params.toString()}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (response.ok) {
                const json = await response.json() as unknown;
                const data = unwrapApiData<AdminLogRecord[]>(json);
                const normalized = Array.isArray(data) ? data : [];

                if (isLoadMore) {
                    setAdminLogs(prev => [...prev, ...normalized]);
                } else {
                    setAdminLogs(normalized);
                }

                const nextPageConfig = {
                    ...currentConfig,
                    offset: currentOffset,
                    hasMore: normalized.length === currentConfig.limit
                };
                pageConfigRef.current = nextPageConfig;
                setPageConfig(nextPageConfig);
            }
        } catch (error) {
            console.error('Failed to fetch admin logs:', error);
        } finally {
            loadingRef.current = false;
            setLoading(false);
        }
    }, []);

    React.useEffect(() => {
        if (activeTab === 'admins' && canViewAdminLogs) {
            void fetchAdminLogs(false);
        }
    }, [activeTab, canViewAdminLogs, fetchAdminLogs]);

    const handleApplyFilters = () => {
        setPageConfig(prev => ({ ...prev, offset: 0, hasMore: true }));
        void fetchAdminLogs(false);
    };

    const handleSort = (key: string) => {
        setSortConfig(prev => ({
            key,
            direction: prev.key === key && prev.direction === 'desc' ? 'asc' : 'desc'
        }));
    };

    React.useEffect(() => {
        if (activeTab === 'admins' && canViewAdminLogs) {
            setPageConfig(prev => ({ ...prev, offset: 0, hasMore: true }));
            void fetchAdminLogs(false);
        }
    }, [activeTab, canViewAdminLogs, sortConfig, fetchAdminLogs]);

    const handleResetFilters = () => {
        setFilters({
            action: [],
            adminName: '',
            targetType: '',
            startDate: '',
            endDate: ''
        });
        setSortConfig({
            key: 'created_at',
            direction: 'desc'
        });
        setPageConfig(prev => ({ ...prev, offset: 0, hasMore: true }));
        void fetchAdminLogs(false);
    };

    const handleCopyLog = (log: AdminLogRecord) => {
        const date = new Date(log.created_at).toLocaleString();
        const details = log.details ? JSON.stringify(log.details, null, 2) : 'Нет деталей';

        const textToCopy = `[ ${date} ] [ ${log.admin_name} | ${log.admin_role} ] [ ${log.action} ]\n\`\`\`md\n${details}\n\`\`\``;

        navigator.clipboard.writeText(textToCopy).then(() => {
            setNotification(`Вы успешно скопировали лог #${log.id}`);
            setTimeout(() => setNotification(null), 2000);
        });
    };

    const actionOptions = [
        { value: '', label: 'Все действия' },
        { value: 'update_streamer', label: 'update_streamer' },
        { value: 'create_event', label: 'create_event' },
        { value: 'delete_streamer', label: 'delete_streamer' },
        { value: 'reg_user', label: 'reg_user' },
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
                <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-8 text-center">
                    <div className="w-16 h-16 rounded-full bg-white/5 flex items-center justify-center mx-auto mb-4">
                        <FileText className="w-8 h-8 text-white/20" />
                    </div>
                    <h3 className="text-xl font-bold text-white mb-2">Логи ассистентов</h3>
                    <p className="text-white/40">Тут что-то будет, что-то когда-то 🐈</p>
                </div>
            )}
            {notification && <NotificationToast message={notification} />}
            {activeTab === 'admins' && canViewAdminLogs && (
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

                    <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden">
                        <div
                            className="h-[600px] overflow-x-auto overflow-y-auto relative flex flex-col"
                            style={{
                                scrollbarWidth: 'auto',
                                scrollbarColor: '#3b82f6 #1e1e1e'
                            }}
                        >
                            <table className="w-full text-left border-collapse">
                                <thead className="sticky top-0 z-20 bg-[#1e1e1e]">
                                    <tr className="border-b border-white/5 bg-white/5">
                                        {[
                                            { key: 'created_at', label: 'Дата' },
                                            { key: 'admin_name', label: 'Админ' },
                                            { key: 'action', label: 'Действие' },
                                            { key: 'target_name', label: 'Цель' }
                                        ].map((col) => (
                                            <th
                                                key={col.key}
                                                onClick={() => handleSort(col.key)}
                                                className="p-4 text-xs font-medium text-white/40 uppercase tracking-wider cursor-pointer select-none hover:text-white transition-colors"
                                            >
                                                <div className="flex items-center gap-1">
                                                    {col.label}
                                                    {sortConfig.key === col.key && (
                                                        sortConfig.direction === 'asc' ? <ArrowUp className="w-3 h-3 text-blue-400" /> : <ArrowDown className="w-3 h-3 text-blue-400" />
                                                    )}
                                                </div>
                                            </th>
                                        ))}
                                        <th className="p-4 text-xs font-medium text-white/40 uppercase tracking-wider text-right">Детали</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-white/5">
                                    {loading ? (
                                        <tr>
                                            <td colSpan={5} className="p-8 text-center text-white/40">Загрузка...</td>
                                        </tr>
                                    ) : adminLogs.length > 0 ? (
                                        adminLogs.map((log) => (
                                            <tr
                                                key={log.id}
                                                className="hover:bg-white/5 transition-colors cursor-pointer select-none"
                                                onDoubleClick={() => handleCopyLog(log)}
                                            >
                                                <td className="p-4 text-sm text-white/60 whitespace-nowrap">
                                                    {new Date(log.created_at).toLocaleString()}
                                                </td>
                                                <td className="p-4">
                                                    <div className="flex items-center gap-2">
                                                        <span className="font-medium text-white">{log.admin_name}</span>
                                                        <span className="text-xs px-2 py-0.5 rounded bg-white/10 text-white/40">{log.admin_role}</span>
                                                    </div>
                                                </td>
                                                <td className="p-4 text-sm font-medium text-white/80">
                                                    {log.action}
                                                </td>
                                                <td className="p-4 text-sm text-white/60">
                                                    <div className="flex flex-col gap-1">
                                                        <span className="font-medium text-white">{log.target_name || log.target_id}</span>
                                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-white/40 w-fit font-mono">
                                                            {log.target_type} #{log.target_id}
                                                        </span>
                                                    </div>
                                                </td>
                                                <td className="p-4 text-right">
                                                    {log.details && (
                                                        <button
                                                            onClick={() => setSelectedLog(log)}
                                                            className="group flex items-center gap-2 ml-auto px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/5 transition-all"
                                                        >
                                                            <span className="text-xs text-white/60 group-hover:text-white">Подробнее</span>
                                                            <Eye className="w-3 h-3 text-white/40 group-hover:text-white" />
                                                        </button>
                                                    )}
                                                </td>
                                            </tr>
                                        ))
                                    ) : (
                                        <tr>
                                            <td colSpan={5} className="p-8 text-center text-white/40">Нет записей</td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>

                            {/* Load More Button */}
                            {pageConfig.hasMore && (
                                <div className="text-center py-4 bg-[#242424]/80 backdrop-blur-sm border-t border-white/5">
                                    <button
                                        onClick={() => void fetchAdminLogs(true)}
                                        disabled={loading}
                                        className="px-6 py-2 bg-white/5 hover:bg-white/10 border border-white/5 rounded-full text-white/60 hover:text-white transition-all text-sm font-medium disabled:opacity-50"
                                    >
                                        {loading ? 'Загрузка...' : 'Загрузить еще'}
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                    {notification && <NotificationToast message={notification} />}

                    <DetailsModal
                        isOpen={!!selectedLog}
                        onClose={() => setSelectedLog(null)}
                        data={selectedLog?.details}
                        title={`Детали лога #${selectedLog?.id}`}
                    />
                </div>
            )}
        </div>
    );
}

export default SpectateLogs;
