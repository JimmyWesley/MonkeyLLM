/** Semantic tokens only (spec J.5.3).
 *
 * Every colour resolves through a CSS variable defined per theme in
 * index.css, so `bg-surface` is right in light and dark without a `dark:`
 * variant anywhere in the component tree. The theme is an attribute on
 * <html>, not a class, so an OS-preference change can repaint without React
 * re-rendering a single component.
 *
 * @type {import('tailwindcss').Config} */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: { DEFAULT: token('bg'), elev: token('bg-elev') },
        surface: {
          DEFAULT: token('surface'),
          2: token('surface-2'),
          3: token('surface-3'),
        },
        line: { DEFAULT: token('line'), strong: token('line-strong') },
        text: {
          DEFAULT: token('text'),
          2: token('text-2'),
          3: token('text-3'),
        },
        accent: {
          DEFAULT: token('accent'),
          hover: token('accent-hover'),
          fg: token('accent-fg'),
          soft: token('accent-soft'),
        },
        danger: { DEFAULT: token('danger'), soft: token('danger-soft') },
        warn: { DEFAULT: token('warn'), soft: token('warn-soft') },
        ok: { DEFAULT: token('ok'), soft: token('ok-soft') },
      },
      fontFamily: {
        sans: ['Inter var', 'Inter', 'ui-sans-serif', 'system-ui',
               '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      boxShadow: {
        card: 'var(--shadow)',
        pop: '0 12px 32px -8px rgb(0 0 0 / 0.18), 0 2px 8px -2px rgb(0 0 0 / 0.10)',
      },
      maxWidth: { content: '78rem' },
    },
  },
  plugins: [],
}
