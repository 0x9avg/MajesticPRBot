import { useNavigate } from 'react-router-dom';
import { Home, AlertTriangle } from 'lucide-react';

export default function NotFound() {
    const navigate = useNavigate();

    return (
        <div className="min-h-screen flex items-center justify-center p-4 relative overflow-hidden bg-[#1a1a1a] text-white">
            <div className="absolute top-0 left-0 w-full h-full overflow-hidden pointer-events-none z-0">
                <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-[#2563eb]/10 rounded-full blur-[100px]" />
                <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-[#e81c5a]/10 rounded-full blur-[100px]" />
            </div>

            <div className="relative z-10 text-center max-w-lg">
                <div className="flex items-center justify-center gap-4 mb-6">
                    <AlertTriangle className="w-24 h-24 text-[#e81c5a] opacity-80" />
                    <h1 className="text-8xl font-black bg-gradient-to-r from-[#3b82f6] to-[#e81c5a] bg-clip-text text-transparent">
                        404
                    </h1>
                </div>

                <h2 className="text-2xl font-bold mb-4 text-white/90">
                    Страница не найдена
                </h2>

                <p className="text-white/60 mb-8">
                    Похоже, вы заблудились в интернете. Страница, которую вы ищете, не существует или была перемещена.
                </p>

                <button
                    onClick={() => navigate('/hub')}
                    className="px-6 py-3 bg-[#2563eb] text-white rounded-xl font-medium transition-all hover:bg-[#3b82f6] active:scale-95 flex items-center justify-center gap-2 mx-auto"
                >
                    <Home className="w-5 h-5" />
                    Вернуться домой
                </button>
            </div>
        </div>
    );
}
