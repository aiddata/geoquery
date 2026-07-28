import tailwindcss from "@tailwindcss/vite";
import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  server: {
    allowedHosts: ["computerx.tail89de66.ts.net"],
    host: '0.0.0.0',
    fs: {
      allow: ['..', '/app/docs'],
    },
    watch: {
      usePolling: true,
    },
    proxy: {
      // changeOrigin must stay false: Django builds absolute URLs (e.g. the
      // GitHub OAuth redirect_uri) from the Host header, which must be the
      // browser-facing origin (localhost:5173), not the proxy target.
      "/api": {
        target: process.env.API_URL || "http://localhost:8000",
        changeOrigin: false,
      },
      "/stats": {
        target: process.env.API_URL || "http://localhost:8000",
        changeOrigin: false,
      },
    },
  },
});
