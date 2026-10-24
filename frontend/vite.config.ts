import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: process.env.BEFORE_OPEN_API_TARGET ?? "http://127.0.0.1:8001", changeOrigin: false } },
  },
});
