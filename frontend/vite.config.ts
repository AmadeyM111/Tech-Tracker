import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev proxy must not rewrite the Host header: the backend compares it
// with the browser Origin (http://localhost:5173), hence changeOrigin: false.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: false,
      },
    },
  },
  test: {
    include: ["tests/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
  },
});
