import { writable } from 'svelte/store';
import {
	getAuthSession,
	logout,
	type AllauthUser,
	type AuthSession
} from '$lib/allauth';

export type AuthState =
	| { status: 'loading' }
	| { status: 'anonymous' }
	| { status: 'authenticated'; user: AllauthUser };

export const auth = writable<AuthState>({ status: 'loading' });

/** Apply a response that already carries the complete authentication state. */
export function setAuthSession(session: AuthSession): void {
	auth.set(
		session.status === 'authenticated'
			? { status: 'authenticated', user: session.user }
			: { status: 'anonymous' }
	);
}

/** Refresh the store and let failures propagate to authentication-critical UI. */
export async function refreshAuth(): Promise<AuthSession> {
	const session = await getAuthSession();
	setAuthSession(session);
	return session;
}

/** Hydrate the store from the backend session. Called from the root layout. */
export async function initAuth(): Promise<void> {
	try {
		await refreshAuth();
	} catch {
		// Backend unreachable — treat as anonymous rather than blocking the UI.
		auth.set({ status: 'anonymous' });
	}
}

export async function signOut(): Promise<void> {
	await logout();
	auth.set({ status: 'anonymous' });
}
