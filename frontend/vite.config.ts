import adapter from "@sveltejs/adapter-node";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";
import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

// Group the shared UI layer (shadcn components, bits-ui and its helpers, Lucide
// icons) into one chunk. Left alone, each becomes its own tiny chunk. SvelteKit 2
// listed every chunk in the response's `link` header, which nginx rejected once
// all headers exceeded its 4 KB proxy_buffer_size; SvelteKit 3 preloads with
// <link> elements instead unless `output.linkHeaderPreload` is set, but the
// grouping still saves the browser a few dozen tiny requests.
const uiChunk = {
  name: "ui",
  test: (id: string) =>
    /[\\/]node_modules[\\/](@lucide[\\/]svelte|bits-ui|runed|svelte-toolbelt|@floating-ui|tabbable|focus-trap)[\\/]/.test(id) ||
    /[\\/]src[\\/]lib[\\/]components[\\/]ui[\\/]/.test(id),
};

export default defineConfig(({ isSsrBuild }) => ({
  plugins: [
    tailwindcss(),
    sveltekit({
      preprocess: vitePreprocess(),
      adapter: adapter(),
    }),
  ],
  build: {
    rolldownOptions: {
      output: { codeSplitting: isSsrBuild ? true : { groups: [uiChunk] } },
    },
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
