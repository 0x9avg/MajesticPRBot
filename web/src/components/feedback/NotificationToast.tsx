import React from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, Check, Info, TriangleAlert } from 'lucide-react';

void React;

export type ToastType = 'success' | 'error' | 'info' | 'warning';

interface NotificationToastProps {
    message: string;
    type?: ToastType;
    onClose?: () => void;
}

const toastStyles: Record<ToastType, {
    borderColor: string;
    shadowColor: string;
    iconBg: string;
    iconColor: string;
    Icon: typeof Check;
}> = {
    success: {
        borderColor: 'border-[#3b82f6]',
        shadowColor: 'shadow-blue-500/10',
        iconBg: 'bg-[#3b82f6]/20',
        iconColor: 'text-[#3b82f6]',
        Icon: Check,
    },
    error: {
        borderColor: 'border-red-500',
        shadowColor: 'shadow-red-500/10',
        iconBg: 'bg-red-500/20',
        iconColor: 'text-red-500',
        Icon: AlertTriangle,
    },
    info: {
        borderColor: 'border-cyan-500',
        shadowColor: 'shadow-cyan-500/10',
        iconBg: 'bg-cyan-500/20',
        iconColor: 'text-cyan-400',
        Icon: Info,
    },
    warning: {
        borderColor: 'border-amber-500',
        shadowColor: 'shadow-amber-500/10',
        iconBg: 'bg-amber-500/20',
        iconColor: 'text-amber-400',
        Icon: TriangleAlert,
    },
};

const NotificationToast = ({ message, type = 'success', onClose }: NotificationToastProps) => {
    if (typeof document === 'undefined') return null;

    const { borderColor, shadowColor, iconBg, iconColor, Icon } = toastStyles[type];

    return createPortal(
        <div
            style={{
                position: 'fixed',
                bottom: '32px',
                left: '50%',
                transform: 'translateX(-50%)',
                zIndex: 2147483647,
                animation: 'fadeIn 0.3s ease-in-out',
            }}
        >
            <div
                onClick={onClose}
                className={`bg-[#121212]/80 border ${borderColor} text-white px-6 py-3 rounded-xl shadow-lg ${shadowColor} flex items-center gap-3 backdrop-blur-md select-none ${onClose ? 'cursor-pointer hover:bg-[#1e1e1e]/80' : ''} transition-colors`}
            >
                <div className={`${iconBg} p-1 rounded-full ${iconColor}`}>
                    <Icon className="w-4 h-4" />
                </div>
                <span className="font-medium text-sm whitespace-nowrap">{message}</span>
            </div>
        </div>,
        document.body,
    );
};

export default NotificationToast;
