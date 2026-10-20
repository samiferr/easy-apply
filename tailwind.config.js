/** @type {import('tailwindcss').Config} */
// The Tonal design system (design/tonal/README.md). Colour roles come from
// design/tonal/tokens.json via the CSS variables in static/src/tokens.css
// (python design/build_tokens.py), so `bg-primary`, `text-on-surface`,
// `bg-surface-container-low` and the rest follow the active theme on their own.
const tonal = require("./design/tonal/tokens.json");

const roles = Object.fromEntries(
  tonal.color.tokens
    .filter((token) => token.name !== "shadow")
    .map((token) => [token.name, `rgb(var(--${token.name}-rgb) / <alpha-value>)`]),
);

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
      fontFamily: {
        sans: ["Roboto", "Helvetica Neue", "Arial", "system-ui", "sans-serif"],
        mono: ["Roboto Mono", "ui-monospace", "SF Mono", "Menlo", "monospace"],
      },
      fontSize: {
        // The `heading-*` steps are the Tonal type scale (size, line height),
        // so a heading moves with the system rather than with a ratio of its
        // own: nothing between two steps is invented.
        "heading-sm": ["16px", "24px"], //   title-medium
        "heading-base": ["22px", "28px"], // title-large
        "heading-lg": ["22px", "28px"], //   title-large
        "heading-xl": ["24px", "32px"], //   headline-small
        "heading-2xl": ["28px", "36px"], //  headline-medium
        "heading-3xl": ["32px", "40px"], //  headline-large
        "heading-4xl": ["36px", "44px"], //  display-small
        "heading-5xl": ["45px", "52px"], //  display-medium
        "heading-6xl": ["57px", "64px"], //  display-large
        "heading-7xl": ["57px", "64px"], //  display-large
        // Tonal label and body steps that Tailwind's scale has no name for.
        "label-lg": ["14px", { lineHeight: "20px", letterSpacing: "0.1px", fontWeight: "500" }],
        "label-md": ["12px", { lineHeight: "16px", letterSpacing: "0.5px", fontWeight: "500" }],
        "label-sm": ["11px", { lineHeight: "16px", letterSpacing: "0.5px", fontWeight: "500" }],
      },
      maxWidth: {
        // Caps the whole app on ultrawide displays: 16rem of sidebar plus an
        // 80rem content column.
        shell: "96rem",
        // ~65 characters, the range long-form text reads most comfortably at.
        measure: "65ch",
      },
      colors: {
        ...roles,
        // Names the app used before Tonal, kept so a stray class still resolves
        // to the right role instead of vanishing.
        canvas: roles.surface,
        "surface-sunken": roles["surface-container-high"],
        line: roles["outline-variant"],
        "line-strong": roles.outline,
      },
      boxShadow: {
        // Tonal elevation levels 0-5. Hierarchy is carried first by surface tone
        // and second by shadow; cards at rest never go past level 1.
        "elevation-1": "0 1px 2px rgba(0,0,0,0.3), 0 1px 3px 1px rgba(0,0,0,0.15)",
        "elevation-2": "0 1px 2px rgba(0,0,0,0.3), 0 2px 6px 2px rgba(0,0,0,0.15)",
        "elevation-3": "0 1px 3px rgba(0,0,0,0.3), 0 4px 8px 3px rgba(0,0,0,0.15)",
        "elevation-4": "0 2px 3px rgba(0,0,0,0.3), 0 6px 10px 4px rgba(0,0,0,0.15)",
        "elevation-5": "0 4px 4px rgba(0,0,0,0.3), 0 8px 12px 6px rgba(0,0,0,0.15)",
        card: "0 1px 2px rgba(0,0,0,0.3), 0 1px 3px 1px rgba(0,0,0,0.15)",
        "card-hover": "0 1px 2px rgba(0,0,0,0.3), 0 2px 6px 2px rgba(0,0,0,0.15)",
      },
      borderRadius: {
        // Tonal shapes that Tailwind's own names do not already cover. The rest
        // line up: rounded-lg 8px = radius-sm, rounded-xl 12px = radius-md,
        // rounded-2xl 16px = radius-lg, rounded-full = radius-full.
        "tn-xs": "4px",
        "tn-dialog": "28px",
      },
    },
  },
  plugins: [
    require("@tailwindcss/forms"),
  ],
};
