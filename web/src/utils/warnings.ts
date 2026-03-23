export const formatAssistantWarnings = (
    strictWarnings?: number | null,
    oralWarnings?: number | null,
): string => {
    const strict = Math.max(Number(strictWarnings || 0), 0);
    const oral = Math.max(Number(oralWarnings || 0), 0);
    return `${strict}/2 ${oral}/2`;
};
