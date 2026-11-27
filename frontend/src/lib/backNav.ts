import { goto, type afterNavigate } from '$app/navigation';

type AfterNavigate = Parameters<Parameters<typeof afterNavigate>[0]>[0];

/**
 * Where each page's Back button goes (GEO-157): the page the visitor was on
 * when they opened it, or a fallback when they arrived some other way (a
 * link from outside, a refresh). Keyed by route id, so moving within a page
 * (a request token in the address) keeps it.
 *
 * Arriving through a Back button records nothing, so a chain unwinds:
 * Customize → Account → Past Requests, then Back, Back, returns to Customize.
 */
const PAGES = new Set([
	'/account',
	'/requests/[[token]]',
	'/requests/[id=uuid]',
	'/legacy/[id=objectid]',
	'/stats'
]);

const returnTo = new Map<string, string>();
let returning = false;

/** Called from the root layout's afterNavigate. */
export function recordReturn({ from, to, type }: Pick<AfterNavigate, 'from' | 'to' | 'type'>): void {
	const viaBack = returning;
	returning = false;
	const id = to?.route.id;
	if (!id || !PAGES.has(id) || viaBack) return;
	// The browser's own back and forward buttons: the page was opened before
	if (type === 'popstate') return;
	if (!from?.route.id || from.route.id === id) return;
	returnTo.set(id, from.url.pathname + from.url.search + from.url.hash);
}

/** The Back button: where the page was opened from, else `fallback`. */
export function goBack(routeId: string | null, fallback = '/'): Promise<void> {
	returning = true;
	return goto((routeId && returnTo.get(routeId)) || fallback);
}

/** For tests. */
export function resetBackNav(): void {
	returnTo.clear();
	returning = false;
}
