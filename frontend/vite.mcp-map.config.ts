import { resolve } from 'node:path';
import { defineConfig } from 'vite';
import { viteSingleFile } from 'vite-plugin-singlefile';

export default defineConfig({
	root: resolve(import.meta.dirname, 'mcp-map'),
	plugins: [viteSingleFile()],
	build: {
		emptyOutDir: false,
		outDir: resolve(import.meta.dirname, '../backend/mcp_server/apps/static'),
		rollupOptions: { input: resolve(import.meta.dirname, 'mcp-map/map-v1.html') },
		target: 'es2022'
	}
});
