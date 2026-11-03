// Kept out of #lib/api so modules tested under `bun test`, which can't resolve
// SvelteKit's $app/env modules, don't import it.
import { PUBLIC_PROTOMAPS_API_KEY } from '$app/env/public';
import { fetchConfig } from '#lib/api.js';

/**
 * The Protomaps key, from the server-rendered env when the frontend is
 * configured with it, so maps don't wait on /api/config/. Falls back to the
 * config fetch while deployments without PUBLIC_PROTOMAPS_API_KEY remain.
 */
export function protomapsApiKey(): Promise<string> {
	if (PUBLIC_PROTOMAPS_API_KEY) return Promise.resolve(PUBLIC_PROTOMAPS_API_KEY);
	return fetchConfig().then((c) => c.protomaps_api_key);
}
