import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// A relative base, so one build works wherever it is served from: at the root of the API
// that mounts it, or under a sub-path on a static host. The page keeps its place in the
// URL fragment, never in the path, so nothing depends on where that root is.
//
// In development the API runs separately; its endpoints are proxied so the page can use
// the same relative URLs it uses when built.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    proxy: {
      "/sessions": "http://localhost:8000",
      "/processes": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
