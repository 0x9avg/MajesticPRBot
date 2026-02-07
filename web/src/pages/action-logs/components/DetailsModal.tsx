
import { FileText, X } from 'lucide-react';

interface DetailsModalProps {
    isOpen: boolean;
    onClose: () => void;
    data: any;
    title: string;
}

const DetailsModal = ({ isOpen, onClose, data, title }: DetailsModalProps) => {
    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]">
            <div className="bg-[#1e1e1e] border border-white/10 rounded-2xl w-full max-w-2xl shadow-2xl transform transition-all scale-100 max-h-[80vh] flex flex-col">
                <div className="flex items-center justify-between p-6 border-b border-white/5">
                    <h3 className="text-xl font-bold text-white flex items-center gap-2">
                        <FileText className="w-5 h-5 text-white/40" />
                        {title}
                    </h3>
                    <button
                        onClick={onClose}
                        className="p-2 hover:bg-white/5 rounded-lg text-white/40 hover:text-white transition-colors"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>
                <div className="p-6 overflow-auto custom-scrollbar">
                    <pre className="bg-black/30 p-4 rounded-xl text-sm font-mono text-white/70 overflow-x-auto whitespace-pre-wrap">
                        {JSON.stringify(data, null, 2)}
                    </pre>
                </div>
                <div className="p-6 border-t border-white/5 flex justify-end">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg transition-colors"
                    >
                        Закрыть
                    </button>
                </div>
            </div>
        </div>
    );
};

export default DetailsModal;
