import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'

const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const appVersion = readFileSync(resolve(rootDir, 'VERSION'), 'utf-8').trim() || '0.0.0-dev'
const devApiTarget = process.env.VITE_DEV_API_TARGET?.trim() || 'http://127.0.0.1:8000'
const allowedHost = process.env.VITE_ALLOWED_HOST?.trim()

export default defineConfig({
    define: {
        __APP_VERSION__: JSON.stringify(appVersion),
    },
    plugins: [react()],
    server: {
        proxy: {
            '/api': {
                target: devApiTarget,
                changeOrigin: true,
            }
        },
        ...(allowedHost ? { allowedHosts: [allowedHost] } : {}),
    }
})
