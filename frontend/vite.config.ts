import tailwindcss from "@tailwindcss/vite";
import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  server: {
    watch: {
      usePolling: true,
    },
    proxy: {
      "/api": {
        target: process.env.API_URL || "http://localhost:8000",
        changeOrigin: true,
      },
      "/stats": {
        target: process.env.API_URL || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
