import React from 'react';
import { useEffect, useState } from 'react';
import { ShieldAlert, AlertCircle, Copy, Check, UserPlus } from 'lucide-react';
import { getMskTodayStr } from '../../../utils/datetime';
import { CustomSelect } from '../../../components/CustomInputs';
import NotificationToast from '../../../components/feedback/NotificationToast';
import { usePopupToast } from '../../../components/feedback/hooks';
import { useOutletContext } from 'react-router-dom';
import type { KnownRole, OutletUserContext } from '../../../types/auth';
import { getApiErrorMessage } from '../../../types/api';
import { apiFetch } from '../../../api/client';

void React;

type Role = KnownRole;

const ROLE_RANK: Record<Role, number> = {
    junior_employee: 0,
    employee: 1,
    senior_employee: 2,
    manager: 3,
    developer: 4,
};

const ROLE_LABELS: Record<Role, string> = {
    junior_employee: 'Младший ассистент',
    employee: 'Ассистент',
    senior_employee: 'Старший ассистент',
    manager: 'Глава ассистентов',
    developer: 'Разработчик',
};

const ALL_ROLES = Object.keys(ROLE_RANK) as Role[];

const getAllowedRoles = (userRole?: Role, canRegisterUsers?: boolean): Role[] => {
    if (!canRegisterUsers || !userRole || ROLE_RANK[userRole] === undefined) {
        return [];
    }

    if (userRole === 'developer') {
        return ALL_ROLES;
    }

    const creatorRank = ROLE_RANK[userRole];
    return ALL_ROLES.filter((role) => ROLE_RANK[role] < creatorRank);
};

const UserRegistration = () => {
    const { user } = useOutletContext<OutletUserContext>();
    const { toast, showToast, closeToast } = usePopupToast(3200);
    const getTodayMskDate = () => getMskTodayStr();
    const [formData, setFormData] = useState({
        username: '',
        nickname: '',
        role: '',
        discord_id: '',
        appointed_at: getTodayMskDate(),
    });
    const [loading, setLoading] = useState(false);
    const [createdUser, setCreatedUser] = useState<{ username: string, password: string } | null>(null);
    const [copied, setCopied] = useState(false);

    const currentUserRole = user?.role as KnownRole | undefined;
    const canRegisterUsers = user?.permissions?.['admin.users.create'] === true;
    const allowedRoles = getAllowedRoles(currentUserRole, canRegisterUsers);
    const roleOptions = allowedRoles.map((role) => ({
        value: role,
        label: ROLE_LABELS[role]
    }));

    useEffect(() => {
        if (formData.role && !allowedRoles.includes(formData.role as Role)) {
            setFormData((prev) => ({ ...prev, role: '' }));
        }
    }, [allowedRoles, formData.role]);

    const handleCopy = () => {
        if (createdUser) {
            navigator.clipboard.writeText(`Login: ${createdUser.username} \nPassword: ${createdUser.password} `)
                .then(() => {
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                    showToast('Данные пользователя скопированы');
                })
                .catch(() => {
                    showToast('Не удалось скопировать данные пользователя', 'error');
                });
        }
    };

    const handleSubmit = async () => {
        try {
            setLoading(true);

            if (!canRegisterUsers) {
                showToast('Недостаточно прав для регистрации пользователей', 'error');
                return;
            }

            // Validate
            if (!formData.username || !formData.nickname || !formData.role || !formData.discord_id || !formData.appointed_at) {
                showToast('Заполните все поля', 'error');
                return;
            }

            // API Call
            const response = await apiFetch('/api/admin/users', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    username: formData.username,
                    nickname: formData.nickname,
                    role: formData.role,
                    discord_id: formData.discord_id,
                    appointed_at: formData.appointed_at,
                })
            });

            const data = await response.json().catch(() => ({} as unknown));

            if (!response.ok) {
                throw new Error(getApiErrorMessage(data, "Ошибка при создании пользователя"));
            }

            const responseData = data as { data?: { username: string; password: string } };
            if (responseData.data?.username && responseData.data?.password) {
                setCreatedUser(responseData.data);
            } else {
                throw new Error("Некорректный ответ сервера при создании пользователя");
            }
            setFormData({
                username: '',
                nickname: '',
                role: '',
                discord_id: '',
                appointed_at: getTodayMskDate(),
            });

        } catch (err: unknown) {
            if (err instanceof Error) {
                showToast(err.message, 'error');
            } else {
                showToast('Ошибка при создании пользователя', 'error');
            }
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="space-y-8 animate-[fadeIn_0.3s_ease-in-out]">
            <div className="flex items-center gap-4 border-b border-white/10 pb-6">
                <div className="w-12 h-12 rounded-xl bg-blue-500/20 text-blue-400 flex items-center justify-center border border-blue-500/30">
                    <UserPlus className="w-6 h-6" />
                </div>
                <div>
                    <h2 className="text-2xl font-bold text-white">Регистрация пользователя</h2>
                    <p className="text-white/60">Добавление нового сотрудника в систему</p>
                </div>
            </div>

            <div className="bg-[#1e1e1e] border border-white/5 rounded-2xl p-6">
                {!canRegisterUsers && (
                    <div className="bg-yellow-500/10 border border-yellow-500/20 text-yellow-300 px-4 py-3 rounded-xl flex items-center gap-3 mb-6">
                        <AlertCircle className="w-5 h-5" />
                        Недостаточно прав для регистрации пользователей
                    </div>
                )}

                {createdUser && (
                    <div className="bg-green-500/10 border border-green-500/20 rounded-xl p-6 mb-6 animate-fade-in relative overflow-hidden group">
                        <div className="absolute top-0 right-0 p-4 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button
                                onClick={handleCopy}
                                className="p-2 hover:bg-green-500/20 rounded-lg text-green-400 transition-colors"
                                title="Копировать данные"
                            >
                                {copied ? <Check className="w-5 h-5" /> : <Copy className="w-5 h-5" />}
                            </button>
                        </div>

                        <div className="flex items-start gap-4">
                            <div className="p-3 bg-green-500/20 rounded-lg">
                                <Check className="w-6 h-6 text-green-400" />
                            </div>
                            <div className="space-y-4 w-full">
                                <div>
                                    <h3 className="text-lg font-semibold text-green-400 mb-1">Пользователь успешно создан!</h3>
                                    <p className="text-green-300/60 text-sm">Сохраните данные для входа, пароль показан единожды.</p>
                                </div>

                                <div className="bg-black/40 rounded-lg p-4 font-mono text-sm space-y-2 border border-green-500/10">
                                    <div className="flex justify-between">
                                        <span className="text-white/40">Login:</span>
                                        <span className="text-white select-all">{createdUser.username}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-white/40">Password:</span>
                                        <span className="text-white select-all font-bold tracking-wider">{createdUser.password}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                <div className="space-y-6">
                    <div className="grid grid-cols-2 gap-6">
                        <div>
                            <label className="text-sm font-medium text-white/60 mb-2 block">Имя пользователя (Login)</label>
                            <input
                                type="text"
                                className="w-full bg-[#2a2a2a] border border-white/5 rounded-xl p-3 text-white focus:outline-none focus:border-blue-500/50 transition-colors"
                                placeholder="user_login"
                                value={formData.username}
                                onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                                disabled={!canRegisterUsers}
                            />
                        </div>
                        <div>
                            <label className="text-sm font-medium text-white/60 mb-2 block">Отображаемое имя (Nickname)</label>
                            <input
                                type="text"
                                className="w-full bg-[#2a2a2a] border border-white/5 rounded-xl p-3 text-white focus:outline-none focus:border-blue-500/50 transition-colors"
                                placeholder="EpikeS"
                                value={formData.nickname}
                                onChange={(e) => setFormData({ ...formData, nickname: e.target.value })}
                                disabled={!canRegisterUsers}
                            />
                        </div>
                    </div>

                    <div className="grid grid-cols-1 gap-6">
                        <div>
                            <label className="text-sm font-medium text-white/60 mb-2 block">Роль</label>
                            {canRegisterUsers ? (
                                <CustomSelect
                                    options={roleOptions}
                                    value={formData.role}
                                    onChange={(value) => setFormData({ ...formData, role: value as string })}
                                    placeholder={roleOptions.length ? "Выберите роль" : "Нет доступных ролей"}
                                    icon={<ShieldAlert className="w-4 h-4" />}
                                />
                            ) : (
                                <div className="w-full bg-[#2a2a2a] border border-white/5 rounded-xl p-3 text-white/40">
                                    Нет доступа
                                </div>
                            )}
                        </div>
                    </div>

                    <div>
                        <label className="text-sm font-medium text-white/60 mb-2 block">Discord ID</label>
                        <input
                            type="text"
                            className="w-full bg-[#2a2a2a] border border-white/5 rounded-xl p-3 text-white focus:outline-none focus:border-blue-500/50 transition-colors"
                            placeholder="000000000000000000"
                            value={formData.discord_id}
                            onChange={(e) => setFormData({ ...formData, discord_id: e.target.value.replace(/\D/g, '') })}
                            disabled={!canRegisterUsers}
                        />
                    </div>

                    <div>
                        <label className="text-sm font-medium text-white/60 mb-2 block">Дата назначения</label>
                        <input
                            type="date"
                            className="w-full bg-[#2a2a2a] border border-white/5 rounded-xl p-3 text-white focus:outline-none focus:border-blue-500/50 transition-colors"
                            value={formData.appointed_at}
                            onChange={(e) => setFormData({ ...formData, appointed_at: e.target.value })}
                            disabled={!canRegisterUsers}
                            required
                        />
                    </div>

                    <div className="pt-4 flex items-center justify-between">
                        <div className="flex items-center gap-3 bg-yellow-500/10 border border-yellow-500/20 px-4 py-3 rounded-lg max-w-sm">
                            <AlertCircle className="w-5 h-5 text-yellow-500 shrink-0" />
                            <p className="text-xs text-yellow-200/80 leading-relaxed">Пароль будет сгенерирован автоматически и показан после создания.</p>
                        </div>
                        <button
                            onClick={handleSubmit}
                            disabled={loading || !canRegisterUsers}
                            className={`px-8 py-3 bg-blue-500 hover:bg-blue-600 text-white font-bold rounded-xl shadow-lg shadow-blue-500/20 transition-all ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
                        >
                            {loading ? 'Создание...' : 'Создать пользователя'}
                        </button>
                    </div>
                </div>
            </div>

            {toast && (
                <NotificationToast
                    message={toast.message}
                    type={toast.type}
                    onClose={closeToast}
                />
            )}
        </div>
    );
};

export default UserRegistration;
