import { apiFetch } from './client';
import { unwrapApiData, getApiErrorMessage } from '../types/api';
import type { GameServerDto, GameServerWriteItem } from '../types/domain';

async function parseJsonResponse<T>(response: Response, fallbackMessage: string): Promise<T> {
    if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(getApiErrorMessage(payload, fallbackMessage));
    }

    const json = await response.json() as unknown;
    return unwrapApiData<T>(json);
}

export async function fetchGameServers(): Promise<GameServerDto[]> {
    const response = await apiFetch('/api/game-servers');
    const data = await parseJsonResponse<GameServerDto[]>(response, 'Не удалось загрузить список серверов');
    return Array.isArray(data) ? data : [];
}

export async function replaceGuildGameServers(items: GameServerWriteItem[]): Promise<GameServerDto[]> {
    const response = await apiFetch('/api/guild/game-servers', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items }),
    });
    const data = await parseJsonResponse<GameServerDto[]>(response, 'Не удалось сохранить список серверов');
    return Array.isArray(data) ? data : [];
}
