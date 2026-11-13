/**
 * When the home page shows the welcome modal: throughout the first browser
 * session that sees it (until dismissed, as before), and never in a later one.
 *
 * localStorage remembers which session first saw it; sessionStorage holds this
 * session's id and the dismissal. Signed-in users skip the modal entirely (see
 * routes/+page.svelte), which also covers a returning user on a new device.
 */

const SEEN_KEY = 'geoquery-welcome-seen';
const SESSION_KEY = 'geoquery-session-id';
const DISMISSED_KEY = 'welcomeDismissed';

type KeyValue = Pick<Storage, 'getItem' | 'setItem'>;
export interface WelcomeStorage {
	local: KeyValue;
	session: KeyValue;
}

function browserStorage(): WelcomeStorage {
	return { local: localStorage, session: sessionStorage };
}

function newId(): string {
	return typeof crypto !== 'undefined' && 'randomUUID' in crypto
		? crypto.randomUUID()
		: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function sessionId(session: KeyValue): string {
	let id = session.getItem(SESSION_KEY);
	if (!id) {
		id = newId();
		session.setItem(SESSION_KEY, id);
	}
	return id;
}

/**
 * Whether this session may show the welcome modal. The first call in a
 * browser's first session records that session as the one that saw it.
 * Storage that throws (blocked site data) falls back to showing it.
 */
export function welcomeEligible(storage: WelcomeStorage = browserStorage()): boolean {
	try {
		if (storage.session.getItem(DISMISSED_KEY)) return false;
		const current = sessionId(storage.session);
		const seenIn = storage.local.getItem(SEEN_KEY);
		if (seenIn === null) {
			storage.local.setItem(SEEN_KEY, current);
			return true;
		}
		return seenIn === current;
	} catch {
		return true;
	}
}

/** Record that the modal was closed, so it stays closed for the rest of this session. */
export function dismissWelcome(storage: WelcomeStorage = browserStorage()): void {
	try {
		storage.session.setItem(DISMISSED_KEY, '1');
	} catch {
		// Nothing to remember it in; it may show again on the next load.
	}
}
