import tailwindcss from "@tailwindcss/vite";
import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

// Group the shared UI layer (shadcn components, bits-ui and its helpers, Lucide
// icons) into one chunk. Left to Rollup, each becomes its own tiny chunk and
// SvelteKit lists every chunk in the response's `link` header, which nginx
// rejects once all headers exceed its 4 KB proxy_buffer_size.
function manualChunks(id: string) {
  if (
    /\/node_modules\/(@lucide\/svelte|bits-ui|runed|svelte-toolbelt|@floating-ui|tabbable|focus-trap)\//.test(id) ||
    id.includes("/src/lib/components/ui/")
  ) {
    return "ui";
  }
}

export default defineConfig(({ isSsrBuild }) => ({
  plugins: [tailwindcss(), sveltekit()],
  build: {
    rollupOptions: { output: { manualChunks: isSsrBuild ? undefined : manualChunks } },
  },
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
    },
  },
}));
