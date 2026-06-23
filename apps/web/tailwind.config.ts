import type { Config } from "tailwindcss";

/**
 * Tailwind reads the SEMANTIC design tokens (CSS variables in shared/styles/tokens.css),
 * never raw hex. Components use classes like `bg-surface text-muted border-border`,
 * and theming (OS-based light/dark + manual override) flips the variables.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        border: "var(--border)",
        text: "var(--text)",
        muted: "var(--text-muted)",
        subtle: "var(--text-subtle)",
        brand: { DEFAULT: "var(--brand)", hover: "var(--brand-hover)" },
        info: "var(--info)",
        demo: "var(--demo)",
        pos: "var(--pos)",
        neg: "var(--neg)",
        "brand-soft": "var(--brand-soft)",
        "sector-agriculture": "var(--sector-agriculture)",
        "sector-energy": "var(--sector-energy)",
        "sector-metal": "var(--sector-metal)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: { card: "12px" },
      boxShadow: {
        card: "var(--shadow)",
        sm2: "var(--shadow-sm)",
      },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "fade-in": { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "translateY(0)" } },
      },
      animation: {
        shimmer: "shimmer 1.4s infinite",
        "fade-in": "fade-in 0.25s ease-out",
      },
    },
  },
  plugins: [],
};

export default config;
