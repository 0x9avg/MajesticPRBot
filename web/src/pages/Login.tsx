import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Lock, User, Eye, EyeOff } from 'lucide-react'
import { getApiErrorMessage } from '../types/api'

export default function Login() {
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [showPassword, setShowPassword] = useState(false)
    const [error, setError] = useState('')
    const [loading, setLoading] = useState(false)
    const navigate = useNavigate()

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault()
        setError('')
        setLoading(true)

        try {
            // Step 1: Login
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            })

            if (!response.ok) {
                const data = await response.json().catch(() => ({} as unknown))
                throw new Error(getApiErrorMessage(data, 'Ошибка авторизации'))
            }

            const { access_token, refresh_token } = await response.json()
            localStorage.setItem('access_token', access_token)
            localStorage.setItem('refresh_token', refresh_token)

            // Step 2: Get user info
            const userResponse = await fetch('/api/auth/me', {
                headers: {
                    'Authorization': `Bearer ${access_token}`
                }
            })

            if (userResponse.status === 401) {
                localStorage.removeItem('access_token')
                localStorage.removeItem('refresh_token')
                localStorage.removeItem('user')
                throw new Error('Сессия недействительна. Выполните вход снова.')
            }

            if (userResponse.ok) {
                const userData = await userResponse.json()
                localStorage.setItem('user', JSON.stringify(userData))
            }

            navigate('/hub')
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : 'Ошибка авторизации')
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="min-h-screen flex items-center justify-center p-4 relative overflow-hidden">
            <div className="login-background">
                <div className="gradient-orb orb-1"></div>
                <div className="gradient-orb orb-2"></div>
                <div className="gradient-orb orb-3"></div>
            </div>

            <div className="w-full max-w-md p-8 bg-[#242424]/50 backdrop-blur-xl rounded-2xl border border-white/5 shadow-2xl animate-[fadeIn_0.5s_ease-in-out]">
                <div className="text-center mb-8">
                    <h1 className="text-3xl font-bold text-center mb-2 bg-gradient-to-r from-[#3b82f6] to-[#e81c5a] bg-clip-text text-transparent select-none">PR control panel</h1>
                    <p className="text-white/60 text-center mb-8 text-sm select-none">Панель управления</p>
                </div>

                {error && (
                    <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-500 text-sm text-center">{error}</div>
                )}

                <form className="space-y-6" onSubmit={handleLogin}>
                    <div className="mb-4">
                        <label className="block text-sm font-medium text-white/60 mb-2 ml-1 select-none">Логин</label>
                        <div className="relative">
                            <input
                                type="text"
                                className="w-full px-4 py-3 bg-[#242424] border border-white/5 rounded-xl text-white placeholder-white/30 transition-all focus:outline-none focus:border-[#3b82f6] focus:ring-1 focus:ring-[#3b82f6] pl-10"
                                placeholder="Введите логин..."
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                required
                            />
                            <User className="absolute left-3 top-1/2 -translate-y-1/2 text-white/60 w-5 h-5 pointer-events-none" />
                        </div>
                    </div>

                    <div className="mb-4">
                        <label className="block text-sm font-medium text-white/60 mb-2 ml-1 select-none">Пароль</label>
                        <div className="relative">
                            <input
                                type={showPassword ? 'text' : 'password'}
                                className="w-full px-4 py-3 bg-[#242424] border border-white/5 rounded-xl text-white placeholder-white/30 transition-all focus:outline-none focus:border-[#3b82f6] focus:ring-1 focus:ring-[#3b82f6] pl-10 pr-10"
                                placeholder="••••••••"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                            />
                            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 text-white/60 w-5 h-5 pointer-events-none" />
                            <button
                                type="button"
                                onClick={() => setShowPassword(!showPassword)}
                                className="absolute right-3 top-1/2 -translate-y-1/2 text-white/60 hover:text-white transition-colors focus:outline-none"
                            >
                                {showPassword ? (
                                    <EyeOff className="w-5 h-5" />
                                ) : (
                                    <Eye className="w-5 h-5" />
                                )}
                            </button>
                        </div>
                    </div>

                    <button
                        type="submit"
                        className="w-full px-4 py-3 bg-[#2563eb] text-white rounded-xl font-medium transition-all hover:bg-[#3b82f6] active:scale-95 focus:outline-none focus:ring-2 focus:ring-[#3b82f6]/50 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 select-none"
                        disabled={loading}
                    >
                        {loading ? (
                            <>
                                <span className="w-5 h-5 border-2 border-white/20 border-t-white rounded-full animate-spin" />
                                Вход...
                            </>
                        ) : (
                            'Войти в систему'
                        )}
                    </button>
                </form>
            </div>
        </div>
    )
}
