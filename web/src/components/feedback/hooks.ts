import React from 'react';
import type { ConfirmDialogOptions, ConfirmDialogProps } from './ConfirmDialog';
import type { ToastType } from './NotificationToast';

type ToastState = {
    id: number;
    message: string;
    type: ToastType;
} | null;

const emptyConfirmProps: ConfirmDialogProps = {
    isOpen: false,
    title: '',
    message: '',
    onConfirm: () => undefined,
    onCancel: () => undefined,
};

export function usePopupToast(defaultDuration = 2400) {
    const [toast, setToast] = React.useState<ToastState>(null);
    const timeoutRef = React.useRef<number | null>(null);

    const closeToast = React.useCallback(() => {
        if (timeoutRef.current !== null) {
            window.clearTimeout(timeoutRef.current);
            timeoutRef.current = null;
        }
        setToast(null);
    }, []);

    const showToast = React.useCallback((
        message: string,
        type: ToastType = 'success',
        duration = defaultDuration,
    ) => {
        if (timeoutRef.current !== null) {
            window.clearTimeout(timeoutRef.current);
        }

        const nextToast = {
            id: Date.now(),
            message,
            type,
        };

        setToast(nextToast);

        if (duration > 0) {
            timeoutRef.current = window.setTimeout(() => {
                setToast((currentToast) => (
                    currentToast?.id === nextToast.id ? null : currentToast
                ));
                timeoutRef.current = null;
            }, duration);
        } else {
            timeoutRef.current = null;
        }
    }, [defaultDuration]);

    React.useEffect(() => (
        () => {
            if (timeoutRef.current !== null) {
                window.clearTimeout(timeoutRef.current);
            }
        }
    ), []);

    return {
        toast,
        showToast,
        closeToast,
    };
}

export function useConfirmDialog() {
    const [dialog, setDialog] = React.useState<ConfirmDialogOptions | null>(null);
    const resolverRef = React.useRef<((confirmed: boolean) => void) | null>(null);

    const resolveDialog = React.useCallback((confirmed: boolean) => {
        const resolve = resolverRef.current;
        resolverRef.current = null;
        setDialog(null);
        resolve?.(confirmed);
    }, []);

    const confirm = React.useCallback((options: ConfirmDialogOptions) => new Promise<boolean>((resolve) => {
        if (resolverRef.current) {
            resolverRef.current(false);
        }
        resolverRef.current = resolve;
        setDialog(options);
    }), []);

    React.useEffect(() => (
        () => {
            if (resolverRef.current) {
                resolverRef.current(false);
            }
        }
    ), []);

    const dialogProps: ConfirmDialogProps = dialog
        ? {
            ...dialog,
            isOpen: true,
            onConfirm: () => resolveDialog(true),
            onCancel: () => resolveDialog(false),
        }
        : emptyConfirmProps;

    return {
        confirm,
        dialogProps,
    };
}
