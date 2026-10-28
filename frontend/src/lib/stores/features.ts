import { derived, readable } from 'svelte/store';
import { browser } from '$app/environment';
import { fetchConfig } from '$lib/api';
import { auth } from '$lib/stores/auth';

/**
 * Names of gated features, mirroring the constants in backend/accounts/features.py.
 * Which of them are still in beta comes from /api/config/, so releasing a feature
 * there opens it here too; drop the name and its checks afterwards.
 */
export type FeatureName =
	| 'browse_boundaries'
	| 'custom_boundaries'
	| 'notebook_export'
	| 'visualize';

export interface Features {
	/** False until both the beta list and the session have loaded. */
	ready: boolean;
	has: (feature: FeatureName) => boolean;
}

// null while loading (and throughout SSR, which can't reach the API); 'unknown'
// if config failed, in which case every feature is treated as beta rather than
// opened to everyone.
const betaFeatures = readable<Set<string> | 'unknown' | null>(null, (set) => {
	if (!browser) return;
	fetchConfig()
		.then((config) => set(new Set(config.beta_features)))
		.catch(() => set('unknown'));
});

export const features = derived([auth, betaFeatures], ([$auth, $beta]): Features => {
	const ready = $auth.status !== 'loading' && $beta !== null;
	const tester = $auth.status === 'authenticated' && $auth.user.is_beta_tester === true;
	return {
		ready,
		has: (feature) =>
			ready && (tester || ($beta instanceof Set && !$beta.has(feature)))
	};
});
