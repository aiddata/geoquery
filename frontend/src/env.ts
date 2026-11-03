import { defineEnvVars } from '@sveltejs/kit/env';

export const variables = defineEnvVars({
	PUBLIC_PROTOMAPS_API_KEY: {
		public: true,
		// Optional: without it, maps fetch the key from /api/config/ instead.
		schema: (value) => value || undefined,
		description: 'Protomaps basemap API key, read when the server starts.'
	}
});
