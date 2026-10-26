import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          blue: "#0878F9",
          "blue-hover": "#0662CC",
          dark: "#071B35",
          navy: "#06182B",
          slate: "#10233F",
          soft: "#F5F9FF",
          border: "#DCE7F5",
        },
      },
    },
  },
  plugins: [],
};

export default config;
