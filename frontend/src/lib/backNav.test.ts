import { beforeEach, describe, expect, mock, test } from 'bun:test';

// goto is SvelteKit's; here it only reports where Back went
const visited: string[] = [];
mock.module('$app/navigation', () => ({
	goto: async (url: string) => {
		visited.push(url);
	}
}));

const { goBack, recordReturn, resetBackNav } = await import('./backNav');

type Type = 'link' | 'goto' | 'popstate' | 'enter';
function nav(from: string | null, to: string, type: Type = 'link') {
	const place = (path: string) => {
		const url = new URL(path, 'https://geoquery.test');
		const id = /^\/requests(\/|$)/.test(url.pathname) ? '/requests/[[token]]' : url.pathname;
		return { url, route: { id } };
	};
	recordReturn({ from: from ? place(from) : null, to: place(to), type } as never);
}

beforeEach(() => {
	resetBackNav();
	visited.length = 0;
});

describe('Back', () => {
	test('returns to the page it was opened from, with its query', async () => {
		nav('/customize?dataset=viirs', '/account');
		await goBack('/account');
		expect(visited).toEqual(['/customize?dataset=viirs']);
	});

	test('falls back when the page was opened directly', async () => {
		nav(null, '/stats', 'enter');
		await goBack('/stats');
		await goBack('/requests/[id=uuid]', '/requests');
		expect(visited).toEqual(['/', '/requests']);
	});

	test('unwinds a chain without looping', async () => {
		nav('/customize', '/account');
		nav('/account', '/requests');
		await goBack('/requests/[[token]]');
		nav('/requests', '/account', 'goto'); // the navigation Back started
		await goBack('/account');
		expect(visited).toEqual(['/account', '/customize']);
	});

	test('moving within the page keeps where it was opened from', async () => {
		nav('/review', '/requests');
		nav('/requests', '/requests/abc123');
		await goBack('/requests/[[token]]');
		expect(visited).toEqual(['/review']);
	});

	test("the browser's back and forward don't change it", async () => {
		nav('/customize', '/account');
		nav('/stats', '/account', 'popstate');
		await goBack('/account');
		expect(visited).toEqual(['/customize']);
	});
});
