import path from "path";
import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    proxy: {
      // WebSocket must be declared before the HTTP entry, or `/api` swallows it.
      "/ws": {
        target: process.env.VITE_BACKEND_URL || "http://127.0.0.1:8010",
        ws: true,
        changeOrigin: true,
      },
      "/api": {
        target: process.env.VITE_BACKEND_URL || "http://127.0.0.1:8010",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
