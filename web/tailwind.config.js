/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0d1117",
        surface: "#161b22",
        border: "#30363d",
        accent: "#00bfff",
        buy: "#22c55e",
        sell: "#ef4444",
        hold: "#fbbf24",
      },
    },
  },
  plugins: [],
}
