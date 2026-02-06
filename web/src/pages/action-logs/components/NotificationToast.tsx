import { createPortal } from 'react-dom';
import { Check } from 'lucide-react';

const NotificationToast = ({ message }: { message: string }) => {
    console.log('NotificationToast rendering:', message);
    return createPortal(
        <div
            style={{
                position: 'fixed',
                bottom: '32px',
                left: '50%',
                transform: 'translateX(-50%)',
                zIndex: 2147483647,
                animation: 'fadeIn 0.3s ease-in-out'
            }}
        >
            <div className="bg-[#121212]/80 border border-[#3b82f6] text-white px-6 py-3 rounded-xl shadow-lg shadow-blue-500/10 flex items-center gap-3 backdrop-blur-md">
                <div className="bg-[#3b82f6]/20 p-1 rounded-full text-[#3b82f6]">
                    <Check className="w-4 h-4" />
                </div>
                <span className="font-medium text-sm">{message}</span>
            </div>
        </div>,
        document.body
    );
};

export default NotificationToast;
