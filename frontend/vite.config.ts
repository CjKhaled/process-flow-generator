import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The page is served by the API at /app, so every asset URL is built under that path.
// In development the API runs separately; its endpoints are proxied so the page can use
// the same relative URLs it uses when built.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    proxy: {
      "/sessions": "http://localhost:8000",
      "/session-processes": "http://localhost:8000",
    },
  },
});
