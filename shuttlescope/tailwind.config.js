/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './src/**/*.{ts,tsx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      screens: {
        'xs': '480px',   // スマホ横持ち
        // sm: 640px (Tailwindデフォルト)
        // md: 768px (iPad縦)
        // lg: 1024px (iPad横)
        'xl': '1200px',  // PC (Tailwindデフォルト1280px → 1200pxに調整)
        '2xl': '1440px', // 広幅PC
      },
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
      },
      borderRadius: {
        // 旧 shadcn 互換 (--radius ベース) は既存クラスのため維持。
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
        // DESIGN_DIRECTION_v2 §4: crisp / minimal radius scale。
        // 新規コンポーネントは rounded-ss-* を使う (bubbly な既定 rounded-* と分離)。
        'ss-sm': 'var(--r-sm)',
        'ss-md': 'var(--r-md)',
        'ss-lg': 'var(--r-lg)',
        'ss-xl': 'var(--r-xl)',
        'ss-pill': 'var(--r-pill)',
      },
      boxShadow: {
        // DESIGN_DIRECTION_v2 §4 elevation scale (light-tuned subtle shadows).
        card: 'var(--e1)',
        'card-hover': 'var(--e2)',
        pop: 'var(--e3)',
        flat: 'var(--e0)',
      },
      transitionDuration: {
        fast: 'var(--dur-fast)',
        base: 'var(--dur-base)',
        slow: 'var(--dur-slow)',
      },
      transitionTimingFunction: {
        out: 'var(--ease-out)',
        'in-out': 'var(--ease-in-out)',
      },
    },
  },
  plugins: [],
}
