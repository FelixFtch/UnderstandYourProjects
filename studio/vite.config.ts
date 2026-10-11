/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev: companion-api (HomeHub) reachable on 127.0.0.1:5120, e.g. via
//   ssh -N -L 127.0.0.1:5120:127.0.0.1:5120 jetson
// Override with STUDIO_API_TARGET.
const target = process.env.STUDIO_API_TARGET || "http://127.0.0.1:5120";

export default defineConfig({
  base: "/studio/",
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 4174,
    proxy: { "/api": { target, changeOrigin: false } },
  },
  test: { environment: "jsdom", include: ["src/**/*.test.{ts,tsx}"] },
});
