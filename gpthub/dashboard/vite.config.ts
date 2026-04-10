import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 3001,
    proxy: {
      "/api": { target: process.env.PROXY_URL || "http://localhost:8000", changeOrigin: true },
      "/v1":  { target: process.env.PROXY_URL || "http://localhost:8000", changeOrigin: true },
    },
  },
});
