/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: [
    "./templates/**/*.html",
    "./*/templates/**/*.html",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        brand: {
          50: "#effefb",
          100: "#c9fdf1",
          200: "#94fae3",
          300: "#57efd2",
          400: "#22d9bc",
          500: "#0abda2",
          600: "#049783",
          700: "#08786a",
          800: "#0c5f56",
          900: "#0e4e48",
          950: "#012e2b",
        },
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 1px 6px -1px rgb(0 0 0 / 0.06)",
      },
    },
  },
  plugins: [
    require("@tailwindcss/forms"),
  ],
};
