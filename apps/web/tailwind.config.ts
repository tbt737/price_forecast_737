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
        "sector-agriculture": "var(--sector-agriculture)",
        "sector-energy": "var(--sector-energy)",
        "sector-metal": "var(--sector-metal)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: { card: "10px" },
    },
  },
  plugins: [],
};

export default config;
