/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: [
    "./templates/**/*.html",
    "./*/templates/**/*.html",
    // Widget classes are assembled in Python, so Tailwind has to scan there too.
    "./*/forms.py",
    "./*/*/forms.py",
  ],
  theme: {
    extend: {
      screens: {
        // Small phones: 390px and under can't fit the wordmark next to the
        // profile, language and account controls.
        xs: "460px",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      maxWidth: {
        // Caps the whole app on ultrawide displays: 16rem of sidebar plus an
        // 80rem content column.
        shell: "96rem",
        // ~65 characters, the range long-form text reads most comfortably at.
        measure: "65ch",
      },
      colors: {
        brand: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          800: "#1e40af",
          900: "#1e3a8a",
          950: "#172554",
        },
        // Theme-aware surfaces, defined as CSS variables in static/src/input.css
        // so a component class no longer needs a `dark:` twin for every colour.
        canvas: "rgb(var(--canvas) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        "surface-sunken": "rgb(var(--surface-sunken) / <alpha-value>)",
        // `line` is decorative; `line-strong` is the one that identifies a form
        // control, so it is held at >= 3:1 against both surfaces (WCAG 1.4.11).
        line: "rgb(var(--line) / <alpha-value>)",
        "line-strong": "rgb(var(--line-strong) / <alpha-value>)",
      },
      boxShadow: {
        // Cards read as raised without an outline: a tight contact shadow plus
        // a wider, softer ambient one.
        card: "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 2px 8px -2px rgb(15 23 42 / 0.06)",
        "card-hover": "0 1px 2px 0 rgb(15 23 42 / 0.05), 0 8px 24px -6px rgb(15 23 42 / 0.12)",
        // The sticky top bar only casts a shadow once content slides under it.
        bar: "0 1px 3px 0 rgb(15 23 42 / 0.06), 0 8px 20px -12px rgb(15 23 42 / 0.14)",
      },
    },
  },
  plugins: [
    require("@tailwindcss/forms"),
  ],
};
