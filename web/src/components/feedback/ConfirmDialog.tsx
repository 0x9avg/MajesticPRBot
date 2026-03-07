import React from 'react';
import { createPortal } from 'react-dom';
import { ShieldAlert, TriangleAlert } from 'lucide-react';

export type ConfirmTone = 'default' | 'danger';

export interface ConfirmDialogOptions {
    title: string;
    message: React.ReactNode;
    confirmLabel?: string;
    cancelLabel?: string;
    tone?: ConfirmTone;
}

export interface ConfirmDialogProps extends ConfirmDialogOptions {
    isOpen: boolean;
    onConfirm: () => void;
    onCancel: () => void;
}

const toneStyles: Record<ConfirmTone, {
    iconWrap: string;
    iconClass: string;
    confirmButton: string;
    Icon: typeof ShieldAlert;
}> = {
    default: {
        iconWrap: 'bg-blue-500/10 border-blue-500/20',
        iconClass: 'text-blue-300',
        confirmButton: 'bg-blue-500/15 border-blue-500/30 text-blue-300 hover:bg-blue-500/25',
        Icon: ShieldAlert,
    },
    danger: {
        iconWrap: 'bg-red-500/10 border-red-500/20',
        iconClass: 'text-red-300',
        confirmButton: 'bg-red-500/15 border-red-500/30 text-red-300 hover:bg-red-500/25',
        Icon: TriangleAlert,
    },
};

const ConfirmDialog = ({
    isOpen,
    title,
    message,
    confirmLabel = 'Подтвердить',
    cancelLabel = 'Отмена',
    tone = 'default',
    onConfirm,
    onCancel,
}: ConfirmDialogProps) => {
    React.useEffect(() => {
        if (!isOpen) return undefined;

        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onCancel();
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, onCancel]);

    if (!isOpen || typeof document === 'undefined') return null;

    const { iconWrap, iconClass, confirmButton, Icon } = toneStyles[tone];

    return createPortal(
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-[fadeIn_0.2s_ease-out]"
            onMouseDown={(event) => {
                if (event.target === event.currentTarget) {
                    onCancel();
                }
            }}
        >
            <div
                className="w-full max-w-lg bg-[#1e1e1e] border border-white/10 rounded-3xl shadow-2xl p-6"
                onMouseDown={(event) => event.stopPropagation()}
            >
                <div className="flex items-start gap-4">
                    <div className={`w-12 h-12 rounded-2xl border flex items-center justify-center ${iconWrap}`}>
                        <Icon className={`w-6 h-6 ${iconClass}`} />
                    </div>
                    <div className="flex-1">
                        <h3 className="text-xl font-bold text-white">{title}</h3>
                        <div className="text-sm text-white/50 mt-2 leading-relaxed">{message}</div>
                    </div>
                </div>

                <div className="flex gap-3 mt-6">
                    <button
                        onClick={onConfirm}
                        className={`flex-1 px-4 py-3 rounded-xl border font-semibold transition-colors ${confirmButton}`}
                    >
                        {confirmLabel}
                    </button>
                    <button
                        onClick={onCancel}
                        className="flex-1 px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white/70 hover:text-white hover:bg-white/10 transition-colors"
                    >
                        {cancelLabel}
                    </button>
                </div>
            </div>
        </div>,
        document.body,
    );
};

export default ConfirmDialog;
