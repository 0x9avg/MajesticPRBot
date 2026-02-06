
import { UserPlus, ShieldAlert, AlertCircle } from 'lucide-react';
import { CustomSelect } from '../../../components/CustomInputs';

const UserRegistration = () => (
    <div className="max-w-2xl mx-auto space-y-8 animate-[fadeIn_0.3s_ease-in-out]">
        <div className="flex items-center gap-4 border-b border-white/10 pb-6">
            <div className="w-12 h-12 rounded-xl bg-blue-500/20 text-blue-400 flex items-center justify-center border border-blue-500/30">
                <UserPlus className="w-6 h-6" />
            </div>
            <div>
                <h2 className="text-2xl font-bold text-white">Регистрация пользователя</h2>
                <p className="text-white/60">Добавление нового сотрудника в систему</p>
            </div>
        </div>

        <div className="space-y-6">
            <div className="grid grid-cols-2 gap-6">
                <div>
                    <label className="text-sm font-medium text-white/60 mb-2 block">Имя пользователя (Login)</label>
                    <input type="text" className="w-full bg-black/20 border border-white/10 rounded-xl p-3 text-white focus:outline-none focus:border-blue-500/50 transition-colors" placeholder="user_login" />
                </div>
                <div>
                    <label className="text-sm font-medium text-white/60 mb-2 block">Отображаемое имя (Nickname)</label>
                    <input type="text" className="w-full bg-black/20 border border-white/10 rounded-xl p-3 text-white focus:outline-none focus:border-blue-500/50 transition-colors" placeholder="Ivan Ivanov" />
                </div>
            </div>

            <div className="grid grid-cols-1 gap-6">
                <div>
                    <label className="text-sm font-medium text-white/60 mb-2 block">Роль</label>
                    <CustomSelect
                        options={[
                            { value: 'junior_employee', label: 'Мл. Сотрудник' },
                            { value: 'employee', label: 'Сотрудник' },
                            { value: 'senior_employee', label: 'Ст. Сотрудник' },
                            { value: 'manager', label: 'Менеджер' },
                            { value: 'developer', label: 'Разработчик' }
                        ]}
                        value={''}
                        onChange={() => { }}
                        placeholder="Выберите роль"
                        icon={<ShieldAlert className="w-4 h-4" />}
                    />
                </div>
            </div>

            <div>
                <label className="text-sm font-medium text-white/60 mb-2 block">Discord ID</label>
                <input type="text" className="w-full bg-black/20 border border-white/10 rounded-xl p-3 text-white focus:outline-none focus:border-blue-500/50 transition-colors" placeholder="000000000000000000" />
            </div>

            <div className="pt-4 flex items-center justify-between">
                <div className="flex items-center gap-3 bg-yellow-500/10 border border-yellow-500/20 px-4 py-3 rounded-lg max-w-sm">
                    <AlertCircle className="w-5 h-5 text-yellow-500 shrink-0" />
                    <p className="text-xs text-yellow-200/80 leading-relaxed">Пароль будет сгенерирован автоматически и показан после создания.</p>
                </div>
                <button className="px-8 py-3 bg-blue-500 hover:bg-blue-600 text-white font-bold rounded-xl shadow-lg shadow-blue-500/20 transition-all">
                    Создать пользователя
                </button>
            </div>
        </div>
    </div>
);

export default UserRegistration;
