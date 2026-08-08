/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        canvas: { DEFAULT: '#0d0f0d', soft: '#141714', card: '#191d19', line: '#252a25' },
        moss: { 50: '#eef6f1', 200: '#bfe0cd', 400: '#6cb98f', 500: '#4a9d71', 600: '#3a7f5b', 900: '#16281e' },
        bark: { 300: '#a8a49a', 400: '#8b877d', 500: '#6d6a61' },
        ember: { 400: '#e08b6f', 500: '#c96a4c' },
      },
      fontFamily: {
        sans: ['Inter var', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      boxShadow: {
        panel: '0 1px 2px rgba(0,0,0,.30), 0 8px 24px -12px rgba(0,0,0,.45)',
        ring: '0 0 0 1px rgba(74,157,113,.25)',
      },
      keyframes: {
        rise: { '0%': { opacity: 0, transform: 'translateY(4px)' }, '100%': { opacity: 1, transform: 'none' } },
      },
      animation: { rise: 'rise .18s ease-out both' },
    },
  },
  plugins: [],
}
