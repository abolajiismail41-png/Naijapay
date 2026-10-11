import process from "node:process";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const target =
  process.env.API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],

  server: {
    port: 5173,

    // Vite forwards /api requests to the backend during development.
    // The browser uses the frontend origin, avoiding development CORS issues.
    proxy: {
      "/api": {
        target,
        changeOrigin: true,
      },
    },

    watch: {
      usePolling: process.env.CHOKIDAR_USEPOLLING === "true",
    },
  },

  build: {
    target: "es2022",

    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          query: ["@tanstack/react-query"],
        },
      },
    },
  },

  test: {
    environment: "node",
  },
});