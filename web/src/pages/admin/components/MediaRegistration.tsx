import { useState } from 'react';
import { Radio, Check, AlertCircle } from 'lucide-react';


const MediaRegistration = () => {
    const [priority, setPriority] = useState(0);
    const [urlInput, setUrlInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);

    const handleRegister = async () => {
        if (!urlInput) {
            setMessage({ type: 'error', text: 'Укажите ссылку на профиль' });
            return;
        }

        setLoading(true);
        setMessage(null);

        try {
            const token = localStorage.getItem('access_token');
            // Use full URL as provided by user
            const fullUrl = urlInput;

            // Backend in URL mode expects 'twitch_url' and 'priority'
            const response = await fetch('/api/streamers', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    twitch_url: fullUrl,
                    priority: priority
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Ошибка при добавлении медиа');
            }

            // 202 Accepted = Verification Pending
            if (response.status === 202) {
                setMessage({ type: 'success', text: `Запрос на добавление отправлен на проверку` });
                setUrlInput('');
            } else {
                setMessage({ type: 'success', text: `Медиа успешно добавлено` });
                setUrlInput('');
            }

        } catch (err: any) {
            setMessage({ type: 'error', text: err.message || 'Произошла ошибка' });
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="space-y-8 animate-[fadeIn_0.3s_ease-in-out]">
            <div className="flex items-center gap-4 border-b border-white/10 pb-6">
                <div className="w-12 h-12 rounded-xl bg-orange-500/20 text-orange-400 flex items-center justify-center border border-orange-500/30">
                    <Radio className="w-6 h-6" />
                </div>
                <div>
                    <h2 className="text-2xl font-bold text-white">Регистрация медиа</h2>
                    <p className="text-white/60">Добавление нового стримера или партнера</p>
                </div>
            </div>

            <div className="bg-[#1e1e1e] border border-white/5 rounded-2xl p-6">
                {message && (
                    <div className={`px-4 py-3 rounded-xl flex items-center gap-3 ${message.type === 'success' ? 'bg-green-500/10 border border-green-500/20 text-green-400' : 'bg-red-500/10 border border-red-500/20 text-red-400'} mb-6`}>
                        {message.type === 'success' ? <Check className="w-5 h-5" /> : <AlertCircle className="w-5 h-5" />}
                        {message.text}
                    </div>
                )}

                <div className="space-y-6">
                    <div>
                        <label className="text-sm font-medium text-white/60 mb-2 block">Ссылка на профиль</label>
                        <input
                            type="text"
                            className="w-full bg-[#2a2a2a] border border-white/5 rounded-xl p-3 text-white focus:outline-none focus:border-orange-500/50 transition-colors"
                            placeholder="https://twitch.tv/..."
                            value={urlInput}
                            onChange={(e) => setUrlInput(e.target.value)}
                        />
                    </div>

                    <div>
                        <label className="text-sm font-medium text-white/60 mb-2 block">Приоритет</label>
                        <div className="flex gap-2">
                            {[0, 1, 2, 3].map(p => (
                                <button
                                    key={p}
                                    onClick={() => setPriority(p)}
                                    className={`flex-1 py-2.5 rounded-lg border font-bold text-sm transition-all ${priority === p
                                        ? p === 0 ? 'border-white/30 bg-white/10 text-white' :
                                            p === 1 ? 'border-green-500/50 bg-green-500/20 text-green-400' :
                                                p === 2 ? 'border-yellow-500/50 bg-yellow-500/20 text-yellow-400' :
                                                    'border-red-500/50 bg-red-500/20 text-red-400'
                                        : 'border-white/5 bg-white/5 text-white/40 hover:bg-white/10'
                                        }`}
                                >
                                    {p}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div className="pt-4 flex justify-end">
                        <button
                            onClick={handleRegister}
                            disabled={loading}
                            className={`px-8 py-3 bg-orange-500 hover:bg-orange-600 text-white font-bold rounded-xl shadow-lg shadow-orange-500/20 transition-all ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
                        >
                            {loading ? 'Добавление...' : 'Добавить медиа'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default MediaRegistration;
