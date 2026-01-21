import { useNavigate, Outlet } from 'react-router-dom';
import { LogOut, User } from 'lucide-react';

export default function MainLayout() {
    const navigate = useNavigate();
    const userRole = 'Developer';

    const handleLogout = () => {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        navigate('/login');
    };

    return (
        <div className="min-h-screen bg-[#1a1a1a] text-white flex flex-col font-sans">
            <header className="fixed top-0 left-0 right-0 z-50 bg-[#1a1a1a]/80 backdrop-blur-md border-b border-white/5 h-16 flex items-center justify-between px-6 lg:px-12">
                <div className="flex items-center gap-4">
                    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#3b82f6] to-[#e81c5a] flex items-center justify-center shadow-lg shadow-primary/20 select-none">
                        <span className="font-bold text-white text-lg select-none">PR</span>
                    </div>
                    <h1 className="text-xl font-bold bg-gradient-to-r from-[#3b82f6] to-[#e81c5a] bg-clip-text text-transparent hidden sm:block select-none">
                        Control Panel
                    </h1>
                </div>

                <div className="flex items-center gap-6">
                    <div className="hidden md:flex items-center gap-3 text-sm">
                        <div className="text-right">
                            <p className="font-medium text-white">Wayne</p>
                            <p className="text-xs text-white/40">{userRole}</p>
                        </div>
                        <div className="w-10 h-10 rounded-full bg-[#242424] border border-white/10 flex items-center justify-center">
                            <User className="w-5 h-5 text-white/60" />
                        </div>
                    </div>

                    <button
                        onClick={handleLogout}
                        className="p-2 hover:bg-white/5 rounded-lg transition-colors text-white/60 hover:text-red-400"
                        title="Выйти"
                    >
                        <LogOut className="w-5 h-5" />
                    </button>
                </div>
            </header>

            <main className="flex-1 pt-24 px-6 lg:px-12 pb-12 relative overflow-hidden">
                <div className="fixed top-0 left-0 w-full h-full pointer-events-none z-0 overflow-hidden">
                    <div className="absolute top-[-10%] left-[-10%] w-[40vw] h-[40vw] bg-[#3b82f6]/5 rounded-full blur-[120px]" />
                    <div className="absolute bottom-[-10%] right-[-10%] w-[30vw] h-[30vw] bg-[#e81c5a]/5 rounded-full blur-[120px]" />
                </div>

                <div className="relative z-10 max-w-7xl mx-auto">
                    <Outlet />
                </div>
            </main>
        </div>
    );
}
