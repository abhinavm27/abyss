import path from "path";
import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
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
  preview: {
    port: 4173,
    // `vite preview` rejects requests whose Host header it doesn't recognise.
    // tailscale serve forwards the tailnet hostname as-is, so it needs to be
    // allowlisted here — this is what unblocks HTTPS access (and therefore
    // microphone permission) via https://gn100-75f8.tailf05681.ts.net.
    allowedHosts: ["gn100-75f8.tailf05681.ts.net"],
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
