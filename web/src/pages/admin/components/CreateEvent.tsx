
import { CalendarPlus, Filter } from 'lucide-react';
import { CustomSelect, CustomDatePicker, CustomTimePicker } from '../../../components/CustomInputs';

const CreateEvent = () => {
    return (
        <div className="max-w-4xl mx-auto space-y-8 animate-[fadeIn_0.3s_ease-in-out]">
            <div className="flex items-center gap-4 border-b border-white/10 pb-6">
                <div className="w-12 h-12 rounded-xl bg-purple-500/20 text-purple-400 flex items-center justify-center border border-purple-500/30">
                    <CalendarPlus className="w-6 h-6" />
                </div>
                <div>
                    <h2 className="text-2xl font-bold text-white">Новое событие</h2>
                    <p className="text-white/60">Создание нового мероприятия или собрания</p>
                </div>
            </div>

            <div className="grid grid-cols-2 gap-8">
                <div className="space-y-6">
                    <div>
                        <label className="text-sm font-medium text-white/60 mb-2 block">Название события</label>
                        <input type="text" className="w-full bg-black/20 border border-white/10 rounded-xl p-3 text-white focus:outline-none focus:border-purple-500/50 transition-colors" placeholder="Например: Собрание" />
                    </div>
                    <div>
                        <label className="text-sm font-medium text-white/60 mb-2 block">Тип события</label>
                        <CustomSelect
                            options={[
                                { value: 'global', label: 'Глобальное МП' },
                                { value: 'local', label: 'Локальное МП' },
                                { value: 'cine', label: 'Пролетка' },
                                { value: 'learn', label: 'Обучение' }
                            ]}
                            value={''}
                            onChange={() => { }}
                            placeholder="Выберите тип"
                            icon={<Filter className="w-4 h-4" />}
                        />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="text-sm font-medium text-white/60 mb-2 block">Дата начала</label>
                            <CustomDatePicker value="" onChange={() => { }} placeholder="ДД.ММ.ГГГГ" />
                        </div>
                        <div>
                            <label className="text-sm font-medium text-white/60 mb-2 block">Время</label>
                            <CustomTimePicker value="" onChange={() => { }} placeholder="--:--" />
                        </div>
                    </div>
                </div>

                <div className="space-y-6">
                    <div>
                        <label className="text-sm font-medium text-white/60 mb-2 block">Описание</label>
                        <textarea className="w-full h-32 bg-black/20 border border-white/10 rounded-xl p-3 text-white focus:outline-none focus:border-purple-500/50 transition-colors resize-none" placeholder="Краткое описание события..." />
                    </div>
                    <div>
                        <label className="text-sm font-medium text-white/60 mb-2 block">Организатор</label>
                        <input type="text" className="w-full bg-black/20 border border-white/10 rounded-xl p-3 text-white focus:outline-none focus:border-purple-500/50 transition-colors" placeholder="Никнейм организатора" />
                    </div>
                </div>
            </div>

            <div className="flex justify-end pt-4">
                <button className="px-8 py-3 bg-purple-500 hover:bg-purple-600 text-white font-bold rounded-xl shadow-lg shadow-purple-500/20 transition-all">
                    Создать событие
                </button>
            </div>
        </div>
    );
}

export default CreateEvent;
