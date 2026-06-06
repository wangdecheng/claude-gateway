import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          base: "var(--color-primary-base)",
          light: "var(--color-primary-light)",
          subtle: "var(--color-primary-subtle)",
        },
        neutral: {
          bg: "var(--color-neutral-bg)",
          surface: "var(--color-neutral-surface)",
          border: "var(--color-neutral-border)",
          "text-primary": "var(--color-neutral-text-primary)",
          "text-secondary": "var(--color-neutral-text-secondary)",
          "text-muted": "var(--color-neutral-text-muted)",
          "code-bg": "var(--color-neutral-code-bg)",
        },
        semantic: {
          success: "var(--color-success)",
          warning: "var(--color-warning)",
          error: "var(--color-error)",
          info: "var(--color-info)",
        },
      },
      fontFamily: {
        primary: ["var(--font-primary)"],
        mono: ["var(--font-mono)"],
      },
      spacing: {
        "1": "var(--space-1)",
        "2": "var(--space-2)",
        "3": "var(--space-3)",
        "4": "var(--space-4)",
        "6": "var(--space-6)",
        "8": "var(--space-8)",
        "12": "var(--space-12)",
        "16": "var(--space-16)",
        "24": "var(--space-24)",
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        full: "var(--radius-full)",
      },
      boxShadow: {
        card: "var(--elevation-card)",
        dropdown: "var(--elevation-dropdown)",
        modal: "var(--elevation-modal)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
