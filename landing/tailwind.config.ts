import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#07111f",
        cyan: "#6ce5f3",
        mint: "#a7f3d0",
      },
    },
  },
  plugins: [],
};

export default config;
