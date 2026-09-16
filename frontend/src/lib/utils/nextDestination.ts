/**
 * Handling for the `next` parameter that carries a user through sign-in.
 *
 * Most destinations are ordinary SvelteKit routes, but one is not: when a chat
 * client connects to the MCP server, Django's OIDC provider sends an
 * unauthenticated browser here with `?next=/api/idp/identity/o/authorize?…`.
 * That path is served by Django, not by SvelteKit, so it needs a real
 * navigation rather than a client-side route change.
 */

import { goto } from '$app/navigation';

export const DEFAULT_NEXT = '/account';

/**
 * Read `next` from a URL, rejecting anything that is not a same-origin path.
 *
 * Only a leading single slash is accepted. `//evil.example` and
 * `https://evil.example` are both absolute references a browser would follow
 * off-site, so they fall back to the default rather than becoming an open
 * redirect out of GeoQuery's sign-in.
 */
export function readNext(url: URL, fallback: string = DEFAULT_NEXT): string {
	const value = url.searchParams.get('next');
	if (!value || !value.startsWith('/') || value.startsWith('//')) return fallback;
	return value;
}

/** True for paths Django serves, which SvelteKit's router cannot resolve. */
export function isServerRoute(destination: string): boolean {
	return (
		destination.startsWith('/api/') ||
		destination.startsWith('/admin/') ||
		destination.startsWith('/stats/')
	);
}

/** Go to a post-sign-in destination, by whichever mechanism it needs. */
export async function navigateNext(destination: string): Promise<void> {
	if (isServerRoute(destination)) {
		// Leaves the SPA entirely; replace so Back does not bounce the user
		// into a spent authorization URL.
		window.location.replace(destination);
		return;
	}
	await goto(destination, { replaceState: true });
}
