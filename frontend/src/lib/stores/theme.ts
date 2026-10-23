import { browser } from '$app/environment';
import { derived, readable, writable } from 'svelte/store';

export type ThemePreference = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

/** localStorage key; app.html reads the same key before first paint. */
export const THEME_STORAGE_KEY = 'gq-theme';

function initialPreference(): ThemePreference {
	if (!browser) return 'system';
	const stored = localStorage.getItem(THEME_STORAGE_KEY);
	return stored === 'light' || stored === 'dark' ? stored : 'system';
}

/** The user's choice. `system` leaves data-theme unset so the CSS follows prefers-color-scheme. */
export const themePreference = writable<ThemePreference>(initialPreference());

if (browser) {
	themePreference.subscribe((pref) => {
		const root = document.documentElement;
		if (pref === 'system') {
			delete root.dataset.theme;
			localStorage.removeItem(THEME_STORAGE_KEY);
		} else {
			root.dataset.theme = pref;
			localStorage.setItem(THEME_STORAGE_KEY, pref);
		}
	});
}

function mediaStore(query: string): import('svelte/store').Readable<boolean> {
	return readable(false, (set) => {
		if (!browser) return;
		const mq = matchMedia(query);
		set(mq.matches);
		const onChange = () => set(mq.matches);
		mq.addEventListener('change', onChange);
		return () => mq.removeEventListener('change', onChange);
	});
}

const systemDark = mediaStore('(prefers-color-scheme: dark)');
const moreContrast = mediaStore('(prefers-contrast: more)');

/** The theme actually in effect. */
export const resolvedTheme = derived<[typeof themePreference, typeof systemDark], ResolvedTheme>(
	[themePreference, systemDark],
	([pref, dark]) => (pref === 'system' ? (dark ? 'dark' : 'light') : pref)
);

/**
 * Changes whenever the resolved CSS tokens may have changed (theme or contrast mode).
 * MapLibre paint and canvas drawing can't read CSS, so they re-run readTokens() on this.
 */
export const tokenScheme = derived([resolvedTheme, moreContrast], ([theme, contrast]) =>
	contrast ? `${theme}-more` : theme
);
