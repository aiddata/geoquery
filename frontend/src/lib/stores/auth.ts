import { writable } from 'svelte/store';
import { getSession, logout, type AllauthUser } from '$lib/allauth';

export type AuthState =
	| { status: 'loading' }
	| { status: 'anonymous' }
	| { status: 'authenticated'; user: AllauthUser };

export const auth = writable<AuthState>({ status: 'loading' });

/** Hydrate the store from the backend session. Called from the root layout. */
export async function initAuth(): Promise<void> {
	try {
		const user = await getSession();
		auth.set(user ? { status: 'authenticated', user } : { status: 'anonymous' });
	} catch {
		// Backend unreachable — treat as anonymous rather than blocking the UI.
		auth.set({ status: 'anonymous' });
	}
}

export async function signOut(): Promise<void> {
	await logout();
	auth.set({ status: 'anonymous' });
}
