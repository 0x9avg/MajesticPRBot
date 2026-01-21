/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                background: '#1a1a1a', // Dark background
                surface: '#242424',    // Card background
                primary: {
                    500: '#3b82f6',      // Blue (Binder-Server)
                    600: '#2563eb',
                },
                highlight: '#e81c5a',  // Pink accent
                text: {
                    main: 'rgba(255, 255, 255, 0.87)',
                    muted: 'rgba(255, 255, 255, 0.60)',
                }
            },
            fontFamily: {
                sans: ['Inter', 'system-ui', 'sans-serif'],
            },
            animation: {
                'fade-in': 'fadeIn 0.5s ease-in-out',
                'slide-up': 'slideUp 0.3s ease-out',
            },
            keyframes: {
                fadeIn: {
                    '0%': { opacity: '0' },
                    '100%': { opacity: '1' },
                },
                slideUp: {
                    '0%': { transform: 'translateY(20px)', opacity: '0' },
                    '100%': { transform: 'translateY(0)', opacity: '1' },
                }
            }
        },
    },
    plugins: [],
}
