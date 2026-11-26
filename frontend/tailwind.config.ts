import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0e1320",
        panel: "#141a2a",
        raised: "#1b2337",
        line: "#273049",
        fg: "#dbe1ec",
        muted: "#8590a8",
        faint: "#5b6580",
        accent: "#ecad0a",
        primary: "#209dd7",
        secondary: "#753991",
        up: "#2fbf71",
        down: "#e5484d",
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', '"IBM Plex Sans KR"', "system-ui", "sans-serif"],
        cond: ['"IBM Plex Sans Condensed"', '"IBM Plex Sans KR"', "system-ui", "sans-serif"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
    },
  },
  plugins: [],
};

export default config;
