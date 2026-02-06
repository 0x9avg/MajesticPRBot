
import { Settings, ShieldAlert, Database } from 'lucide-react';

const SiteManagement = () => (
    <div className="space-y-8 animate-[fadeIn_0.3s_ease-in-out]">
        <div className="flex items-center gap-4 border-b border-white/10 pb-6">
            <div className="w-12 h-12 rounded-xl bg-red-500/20 text-red-400 flex items-center justify-center border border-red-500/30">
                <Settings className="w-6 h-6" />
            </div>
            <div>
                <h2 className="text-2xl font-bold text-white">Управление сайтом</h2>
                <p className="text-white/60">Глобальные настройки и права доступа</p>
            </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {/* Maintenance Mode */}
            <div className="bg-[#1e1e1e] border border-white/5 rounded-2xl p-6 relative overflow-hidden group">
                <div className="absolute inset-0 bg-red-500/5 opacity-0 group-hover:opacity-100 transition-opacity" />
                <div className="relative z-10 flex items-start justify-between">
                    <div>
                        <div className="flex items-center gap-3 mb-2">
                            <ShieldAlert className="w-6 h-6 text-red-500" />
                            <h3 className="text-lg font-bold text-white">Режим тех. работ</h3>
                        </div>
                        <p className="text-sm text-white/60 max-w-sm mb-6">
                            Когда включено, доступ к сайту имеют только пользователи с ролью Developer и Manager.
                        </p>
                    </div>
                    <div className="flex flex-col items-center gap-2">
                        <div className="w-14 h-8 bg-white/10 rounded-full relative cursor-pointer hover:bg-white/20 transition-colors">
                            <div className="absolute left-1 top-1 bottom-1 w-6 bg-white/40 rounded-full transition-all" />
                        </div>
                        <span className="text-xs font-mono text-white/40 uppercase">Offline</span>
                    </div>
                </div>
            </div>

            {/* Permission Preset */}
            <div className="bg-[#1e1e1e] border border-white/5 rounded-2xl p-6">
                <div className="flex items-center gap-3 mb-4">
                    <Database className="w-6 h-6 text-blue-500" />
                    <h3 className="text-lg font-bold text-white">Пресеты прав</h3>
                </div>
                <div className="space-y-3">
                    <div className="flex items-center justify-between p-3 bg-white/5 rounded-lg">
                        <span className="text-white/80">Стандартный (Read Only)</span>
                        <button className="text-xs bg-white/10 hover:bg-white/20 px-3 py-1.5 rounded text-white transition-colors">Применить</button>
                    </div>
                    <div className="flex items-center justify-between p-3 bg-white/5 rounded-lg">
                        <span className="text-white/80">Расширенный (Editors)</span>
                        <button className="text-xs bg-white/10 hover:bg-white/20 px-3 py-1.5 rounded text-white transition-colors">Применить</button>
                    </div>
                </div>
            </div>
        </div>

        {/* Permissions Table Mock */}
        <div className="bg-[#1e1e1e] border border-white/5 rounded-2xl p-6">
            <h3 className="text-lg font-bold text-white mb-6">Матрица доступа</h3>
            <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                    <thead>
                        <tr className="text-white/40 border-b border-white/5">
                            <th className="py-3 px-4">Permission</th>
                            <th className="py-3 px-4 text-center">Junior</th>
                            <th className="py-3 px-4 text-center">Employee</th>
                            <th className="py-3 px-4 text-center">Manager</th>
                            <th className="py-3 px-4 text-center">Admin</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                        {['view_logs', 'create_event', 'edit_users', 'manage_site'].map(perm => (
                            <tr key={perm} className="hover:bg-white/5">
                                <td className="py-3 px-4 font-mono text-white/80">{perm}</td>
                                {[0, 1, 2, 3].map((i) => (
                                    <td key={i} className="py-3 px-4 text-center">
                                        <div className={`w-4 h-4 rounded-full mx-auto ${i > 1 ? 'bg-green-500' : 'bg-red-500/20'}`} />
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
);

export default SiteManagement;
