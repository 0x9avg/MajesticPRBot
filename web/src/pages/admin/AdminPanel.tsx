import React from 'react';
import { UserPlus, Radio, CalendarPlus, Settings, Activity, Wrench, Clock } from 'lucide-react';
import UserRegistration from './components/UserRegistration';
import MediaRegistration from './components/MediaRegistration';
import CreateEvent from './components/CreateEvent';
import SiteManagement from './components/SiteManagement';
import SystemInfo from './components/SystemInfo';
import AssistantsManagement from './components/AssistantsManagement';
import PendingRequests from './components/PendingRequests';

export function AdminPanel() {
    const [activeTab, setActiveTab] = React.useState('assistants');

    const menuItems = [
        { id: 'users', label: 'Пользователи', icon: UserPlus },
        { id: 'media', label: 'Медиа', icon: Radio },
        { id: 'events', label: 'Мероприятия', icon: CalendarPlus },
        { id: 'requests', label: 'Запросы', icon: Clock },
        { id: 'assistants', label: 'Ассистенты', icon: Wrench },
        { id: 'site', label: 'Управление', icon: Settings },
        { id: 'system', label: 'Система', icon: Activity },
    ];

    return (
        <div className="flex gap-6 h-[calc(100vh-140px)] animate-[fadeIn_0.5s_ease-out]">
            {/* Sidebar */}
            <div className="w-64 shrink-0 flex flex-col">
                <div className="bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-4 flex flex-col gap-2 h-full">
                    <div className="px-4 py-2 mb-2">
                        <span className="text-xs font-bold text-white/40 uppercase tracking-wider">Меню</span>
                    </div>
                    {menuItems.map(item => (
                        <button
                            key={item.id}
                            onClick={() => setActiveTab(item.id)}
                            className={`flex items-center gap-3 w-full p-3 rounded-xl font-medium transition-all text-left group ${activeTab === item.id
                                ? 'bg-[#3b82f6]/10 text-[#3b82f6] border border-[#3b82f6]/20 shadow-[0_0_15px_rgba(59,130,246,0.1)]'
                                : 'text-white/60 hover:text-white hover:bg-white/5 border border-transparent'
                                }`}
                        >
                            <item.icon className={`w-5 h-5 transition-colors ${activeTab === item.id ? 'text-[#3b82f6]' : 'text-white/40 group-hover:text-white'}`} />
                            {item.label}
                        </button>
                    ))}

                    <div className="mt-auto pt-4 border-t border-white/5">
                        <div className="px-4 py-3 bg-white/5 rounded-xl border border-white/5">
                            <div className="text-xs text-white/40 mb-1">Версия сервера</div>
                            <div className="font-mono text-white/80 text-sm">v1.1.0-DEV</div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 bg-[#242424]/50 backdrop-blur-sm border border-white/5 rounded-2xl p-8 overflow-y-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:'none'] [scrollbar-width:'none'] relative">
                <div className="absolute inset-0 bg-gradient-to-tr from-[#3b82f6]/5 via-transparent to-purple-500/5 pointer-events-none" />
                <div className="relative z-10">
                    {activeTab === 'users' && <UserRegistration />}
                    {activeTab === 'media' && <MediaRegistration />}
                    {activeTab === 'events' && <CreateEvent />}
                    {activeTab === 'requests' && <PendingRequests />}
                    {activeTab === 'assistants' && <AssistantsManagement />}
                    {activeTab === 'site' && <SiteManagement />}
                    {activeTab === 'system' && <SystemInfo />}
                </div>
            </div>
        </div>
    );
}

export default AdminPanel;
