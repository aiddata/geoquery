import { get } from 'svelte/store';
import { auth } from './auth.js';
import { themePreference, type ThemePreference } from './theme.js';
import { saveThemePreference } from '../api.js';

const isTheme = (v: unknown): v is ThemePreference => v === 'system' || v === 'light' || v === 'dark';

/**
 * Keep the theme with the account, so it follows a signed-in user between
 * devices. Signed out, it stays in this browser's localStorage (stores/theme).
 *
 * - On signing in (or loading signed in), the account's theme applies. An
 *   account that never chose one gets this device's current choice saved to
 *   it, rather than a default overriding what the user already picked here.
 * - Changes made while signed in are saved to the account.
 *
 * Called once from the root layout. Returns an unsubscribe function.
 */
export function syncThemeWithAccount(): () => void {
	let userId: number | null = null;
	// Set while the account's theme is being applied, so it isn't saved straight back
	let applying = false;

	const save = (theme: ThemePreference) => {
		saveThemePreference(theme)
			.then(() =>
				auth.update((s) => (s.status === 'authenticated' ? { ...s, user: { ...s.user, theme } } : s))
			)
			.catch(() => {
				// Not fatal: the choice still applies in this browser
			});
	};

	const stopAuth = auth.subscribe((state) => {
		if (state.status !== 'authenticated') {
			if (state.status === 'anonymous') userId = null;
			return;
		}
		if (state.user.id === userId) return; // the same session, refreshed
		userId = state.user.id;
		if (isTheme(state.user.theme)) {
			applying = true;
			themePreference.set(state.user.theme);
			applying = false;
		} else {
			save(get(themePreference));
		}
	});

	let first = true;
	const stopTheme = themePreference.subscribe((theme) => {
		if (first) {
			first = false; // the current value, not a change
			return;
		}
		if (userId !== null && !applying) save(theme);
	});

	return () => {
		stopAuth();
		stopTheme();
	};
}
