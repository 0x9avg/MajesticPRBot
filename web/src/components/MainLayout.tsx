import { useNavigate, Outlet } from 'react-router-dom';
import { LogOut, User } from 'lucide-react';
import { useState, useEffect } from 'react';

interface UserData {
    id: number;
    discord_id: string;
    username: string;
    nickname: string;
    role: string;
    require_password_change: boolean;
}

export default function MainLayout() {
    const navigate = useNavigate();
    const [user, setUser] = useState<UserData | null>(null);

    useEffect(() => {
        const fetchUserData = async () => {
            try {
                const token = localStorage.getItem('access_token');
                if (!token) return;

                // 1. Get Base User Info
                const authRes = await fetch('/api/auth/me', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });

                if (!authRes.ok) return; // Don't logout on background fetch error
                const authUser = await authRes.json();

                // Default to auth info
                let finalUserData = { ...authUser };

                // 2. Try fetching full assistant data (matches UserProfile logic)
                try {
                    // Try by ID first
                    const assistantRes = await fetch(`/api/assistants/${authUser.discord_id}`);
                    if (assistantRes.ok) {
                        const json = await assistantRes.json();
                        const assistantData = json.data || json;
                        if (assistantData) {
                            finalUserData = { ...finalUserData, ...assistantData };
                        }
                    } else {
                        // Fallback: Try finding by nickname
                        const allRes = await fetch('/api/assistants');
                        if (allRes.ok) {
                            const allJson = await allRes.json();
                            const allData = allJson.data || allJson;
                            const found = (Array.isArray(allData) ? allData : []).find((a: any) =>
                                a.nickname.toLowerCase() === authUser.nickname.toLowerCase()
                            );
                            if (found) {
                                finalUserData = { ...finalUserData, ...found };
                            }
                        }
                    }
                } catch (e) {
                    console.warn("Failed to fetch extended assistant data", e);
                }

                // Update state and storage
                setUser(finalUserData);
                localStorage.setItem('user', JSON.stringify(finalUserData));

            } catch (err) {
                console.error('Failed to update user data:', err);
            }
        };

        // Load initially from storage
        const userJson = localStorage.getItem('user');
        if (userJson) {
            try {
                setUser(JSON.parse(userJson));
            } catch (err) { /* ignore */ }
        }

        // Then refresh from network
        fetchUserData();
    }, []);

    const handleLogout = () => {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
        navigate('/login');
    };

    return (
        <div className="min-h-screen bg-[#1a1a1a] text-white flex flex-col font-sans">
            <header className="fixed top-0 left-0 right-0 z-50 bg-[#1a1a1a]/80 backdrop-blur-md border-b border-white/5 h-16 flex items-center justify-between px-6 lg:px-12">
                <div
                    className="flex items-center gap-4 cursor-pointer hover:opacity-80 transition-opacity"
                    onClick={() => navigate('/hub')}
                >
                    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#3b82f6] to-[#e81c5a] flex items-center justify-center shadow-lg shadow-primary/20 select-none">
                        <span className="font-bold text-white text-lg select-none">PR</span>
                    </div>
                    <h1 className="text-xl font-bold bg-gradient-to-r from-[#3b82f6] to-[#e81c5a] bg-clip-text text-transparent hidden sm:block select-none">
                        Control Panel
                    </h1>
                </div>

                <div className="flex items-center gap-6">
                    <button
                        onClick={() => navigate('/profile')}
                        className="hidden md:flex items-center gap-3 text-sm hover:bg-white/5 p-2 rounded-xl transition-all group cursor-pointer"
                    >
                        <div className="text-right">
                            <p className="font-medium text-white group-hover:text-[#3b82f6] transition-colors">
                                {user?.nickname || 'Загрузка...'}
                            </p>
                            <p className="text-xs text-white/40">{user?.role || 'N/A'}</p>
                        </div>
                        <div className="w-10 h-10 rounded-full bg-[#242424] border border-white/10 flex items-center justify-center group-hover:border-[#3b82f6]/50 transition-colors">
                            <User className="w-5 h-5 text-white/60 group-hover:text-[#3b82f6] transition-colors" />
                        </div>
                    </button>

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
                    <Outlet context={{ user }} />
                </div>
            </main>
        </div>
    );
}
