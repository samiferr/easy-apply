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
      fontSize: {
        // Headings run 30% above Tailwind's body scale. Each entry below is
        // the step it is named after multiplied by 1.3 — size and leading
        // together, so a heading's type block keeps its proportions and a
        // two-line title does not crowd itself. Unitless leading (the display
        // steps, which ship at `1`) stays put; there is nothing to scale.
        //
        // They live here rather than as `text-[1.95rem]` at each call site so
        // the ratio is stated once and the next change is one edit.
        "heading-base": ["1.3rem", "1.95rem"], //    text-base  1rem     / 1.5rem
        "heading-sm": ["1.1375rem", "1.625rem"], //  text-sm    0.875rem / 1.25rem
        "heading-lg": ["1.4625rem", "2.275rem"], //  text-lg    1.125rem / 1.75rem
        "heading-xl": ["1.625rem", "2.275rem"], //   text-xl    1.25rem  / 1.75rem
        "heading-2xl": ["1.95rem", "2.6rem"], //     text-2xl   1.5rem   / 2rem
        "heading-3xl": ["2.4375rem", "2.925rem"], // text-3xl   1.875rem / 2.25rem
        "heading-4xl": ["2.925rem", "3.25rem"], //   text-4xl   2.25rem  / 2.5rem
        "heading-5xl": ["3.9rem", "1"], //           text-5xl   3rem     / 1
        "heading-6xl": ["4.875rem", "1"], //         text-6xl   3.75rem  / 1
        "heading-7xl": ["5.85rem", "1"], //          text-7xl   4.5rem   / 1
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
