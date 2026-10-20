/** @type {import('tailwindcss').Config} */
// The Lumen design system (design/lumen/README.md). Semantic colours come from
// design/lumen/tokens.json via the CSS variables in static/src/tokens.css
// (python design/build_tokens.py), so `bg-background-layer-2`,
// `text-content-default`, `bg-accent-background` and the rest follow the active
// theme on their own. Palette steps (`gray-500`, `blue-900`) are left out on
// purpose: they are for charts and illustration only, through `var(--…)`.
const lumen = require("./design/lumen/tokens.json");

const PALETTE = /^(gray|blue|red|orange|yellow|chartreuse|celery|green|seafoam|cyan|indigo|purple|fuchsia|magenta|pink|turquoise|cinnamon|brown|silver)-\d+$/;

const opaque = (value) => /^(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}|\{[a-z0-9-]+\})$/.test(value);

const colors = Object.fromEntries(
  lumen.color.tokens
    .filter((token) => !PALETTE.test(token.name))
    .map((token) => {
      const values = typeof token.value === "string" ? [token.value] : Object.values(token.value);
      // Tokens that carry their own alpha (row-hover, scrim, ...) are used as is;
      // the rest go through their -rgb channels so `/10` modifiers work.
      const value = values.every(opaque)
        ? `rgb(var(--${token.name}-rgb) / <alpha-value>)`
        : `var(--${token.name})`;
      return [token.name, value];
    }),
);

// Lumen type styles: [size, {lineHeight, fontWeight}]. Headings are 800 and
// titles 700, so `text-heading-l` is a whole style, not just a size.
const fontSize = Object.fromEntries(
  lumen.type.groups.flatMap((group) =>
    group.styles.map((style) => [
      style.name,
      [style.fontSize, { lineHeight: String(style.lineHeight), fontWeight: String(style.fontWeight) }],
    ]),
  ),
);

const fromTokens = (family) =>
  Object.fromEntries(lumen[family].tokens.map((token) => [token.name, `var(--${token.name})`]));

module.exports = {
  darkMode: "class",
  content: [
    "./templates/**/*.html",
    "./*/templates/**/*.html",
    // Widget classes are assembled in Python, so Tailwind has to scan there too.
    "./*/forms.py",
    "./*/*/forms.py",
    "./core/templatetags/*.py",
    "./staffportal/templatetags/*.py",
    "./static/js/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["\"Source Sans 3\"", "\"Source Sans Pro\"", "system-ui", "-apple-system", "\"Segoe UI\"", "Roboto", "sans-serif"],
        mono: ["\"Source Code Pro\"", "ui-monospace", "Menlo", "Consolas", "monospace"],
      },
      fontSize,
      colors,
      spacing: fromTokens("spacing"),
      height: fromTokens("height"),
      width: fromTokens("height"),
      minHeight: fromTokens("height"),
      borderRadius: fromTokens("radius"),
      boxShadow: {
        emphasized: "var(--shadow-emphasized)",
        elevated: "var(--shadow-elevated)",
        dragged: "var(--shadow-dragged)",
      },
      maxWidth: {
        // Caps the whole app on ultrawide displays: 16rem of sidebar plus an
        // 80rem content column.
        shell: "96rem",
        // ~65 characters, the range long-form text reads most comfortably at.
        measure: "65ch",
      },
      transitionDuration: {
        // Lumen: hover and press change colour over 130ms.
        DEFAULT: "130ms",
      },
    },
  },
  plugins: [require("@tailwindcss/forms")],
};
