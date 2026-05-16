import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      colors: {
        mission: {
          bg: "#060b14",
          panel: "#0d1a2d",
          border: "rgba(255,255,255,0.07)",
          accent: "#22d3ee",
          alert: "#f97316",
          danger: "#ef4444",
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
