import { createPortal } from 'react-dom';
import { Check, AlertTriangle } from 'lucide-react';

interface NotificationToastProps {
    message: string;
    type?: 'success' | 'error';
    onClose?: () => void;
}

const NotificationToast = ({ message, type = 'success', onClose }: NotificationToastProps) => {
    const isError = type === 'error';
    const borderColor = isError ? 'border-red-500' : 'border-[#3b82f6]';
    const shadowColor = isError ? 'shadow-red-500/10' : 'shadow-blue-500/10';
    const iconBg = isError ? 'bg-red-500/20' : 'bg-[#3b82f6]/20';
    const iconColor = isError ? 'text-red-500' : 'text-[#3b82f6]';

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
            <div
                onClick={onClose}
                className={`bg-[#121212]/80 border ${borderColor} text-white px-6 py-3 rounded-xl shadow-lg ${shadowColor} flex items-center gap-3 backdrop-blur-md select-none cursor-pointer hover:bg-[#1e1e1e]/80 transition-colors`}
            >
                <div className={`${iconBg} p-1 rounded-full ${iconColor}`}>
                    {isError ? <AlertTriangle className="w-4 h-4" /> : <Check className="w-4 h-4" />}
                </div>
                <span className="font-medium text-sm">{message}</span>
            </div>
        </div>,
        document.body
    );
};

export default NotificationToast;
