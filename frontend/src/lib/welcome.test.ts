import { describe, expect, test } from 'bun:test';
import { dismissWelcome, welcomeEligible, type WelcomeStorage } from './welcome';

function memory(): Storage {
	const data = new Map<string, string>();
	return {
		getItem: (k: string) => data.get(k) ?? null,
		setItem: (k: string, v: string) => void data.set(k, v)
	} as Storage;
}

/** One browser: localStorage persists, each session gets a fresh sessionStorage. */
function browser() {
	const local = memory();
	return { newSession: (): WelcomeStorage => ({ local, session: memory() }) };
}

describe('welcomeEligible', () => {
	test('shows in the first session', () => {
		expect(welcomeEligible(browser().newSession())).toBe(true);
	});

	test('keeps showing in the first session until dismissed', () => {
		const s = browser().newSession();
		expect(welcomeEligible(s)).toBe(true);
		expect(welcomeEligible(s)).toBe(true);
		dismissWelcome(s);
		expect(welcomeEligible(s)).toBe(false);
	});

	test('never shows in a later session, dismissed or not', () => {
		const b = browser();
		expect(welcomeEligible(b.newSession())).toBe(true);
		expect(welcomeEligible(b.newSession())).toBe(false);
	});

	test('shows when storage is blocked', () => {
		const blocked = {
			getItem: () => {
				throw new Error('SecurityError');
			},
			setItem: () => {
				throw new Error('SecurityError');
			}
		};
		expect(welcomeEligible({ local: blocked, session: blocked })).toBe(true);
		expect(() => dismissWelcome({ local: blocked, session: blocked })).not.toThrow();
	});
});
