import React from 'react';
import { fetchGameServers } from '../api/gameServers';
import type { GameServerDto } from '../types/domain';

export function useGameServers() {
    const [servers, setServers] = React.useState<GameServerDto[]>([]);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState<string | null>(null);

    const serversById = React.useMemo(() => {
        return Object.fromEntries(servers.map((server) => [server.id, server])) as Record<number, GameServerDto>;
    }, [servers]);

    const reload = React.useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await fetchGameServers();
            setServers(data);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Не удалось загрузить список серверов');
        } finally {
            setLoading(false);
        }
    }, []);

    React.useEffect(() => {
        void reload();
    }, [reload]);

    return {
        servers,
        serversById,
        loading,
        error,
        reload,
    };
}
