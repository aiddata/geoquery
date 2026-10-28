// Kept out of $lib/api so modules tested under `bun test`, which can't resolve
// SvelteKit's $env modules, don't import it.
import { env } from '$env/dynamic/public';
import { fetchConfig } from '$lib/api';

/**
 * The Protomaps key, from the server-rendered env when the frontend is
 * configured with it, so maps don't wait on /api/config/. Falls back to the
 * config fetch while deployments without PUBLIC_PROTOMAPS_API_KEY remain.
 */
export function protomapsApiKey(): Promise<string> {
	if (env.PUBLIC_PROTOMAPS_API_KEY) return Promise.resolve(env.PUBLIC_PROTOMAPS_API_KEY);
	return fetchConfig().then((c) => c.protomaps_api_key);
}
