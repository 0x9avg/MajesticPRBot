
import { Activity, Cpu, Layout, CalendarPlus, AlertCircle } from 'lucide-react';

const SystemInfo = () => (
    <div className="space-y-8 animate-[fadeIn_0.3s_ease-in-out]">
        <div className="flex items-center gap-4 border-b border-white/10 pb-6">
            <div className="w-12 h-12 rounded-xl bg-teal-500/20 text-teal-400 flex items-center justify-center border border-teal-500/30">
                <Activity className="w-6 h-6" />
            </div>
            <div>
                <h2 className="text-2xl font-bold text-white">Системная информация</h2>
                <p className="text-white/60">Мониторинг ресурсов и логи сервера</p>
            </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
                { label: 'CPU Load', value: '12%', icon: Cpu, color: 'blue' },
                { label: 'RAM Usage', value: '2.4 GB', icon: Layout, color: 'purple' },
                { label: 'Uptime', value: '4d 12h', icon: CalendarPlus, color: 'green' },
                { label: 'Errors (24h)', value: '0', icon: AlertCircle, color: 'red' }
            ].map((stat, i) => (
                <div key={i} className="bg-[#1e1e1e] border border-white/5 p-4 rounded-xl flex items-center gap-4">
                    <div className={`p-3 rounded-lg bg-${stat.color}-500/10 text-${stat.color}-500`}>
                        <stat.icon className="w-5 h-5" />
                    </div>
                    <div>
                        <div className="text-2xl font-bold text-white">{stat.value}</div>
                        <div className="text-xs text-white/40">{stat.label}</div>
                    </div>
                </div>
            ))}
        </div>

    </div>
);

export default SystemInfo;
