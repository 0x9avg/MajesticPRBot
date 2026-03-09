export const APP_TITLE = 'PR Majestic'

export function formatDocumentTitle(parts: string[]) {
    const normalizedParts = parts.map((part) => part.trim()).filter(Boolean)

    if (normalizedParts.length === 0) {
        return APP_TITLE
    }

    return [...normalizedParts, APP_TITLE].join(' • ')
}
