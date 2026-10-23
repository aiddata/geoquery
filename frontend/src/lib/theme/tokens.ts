/**
 * Resolve design-system tokens (routes/layout.css) to concrete values.
 *
 * MapLibre paint properties and canvas drawing can't read CSS custom properties,
 * so they call this at draw time and again when `tokenScheme` changes.
 */
export interface Tokens {
	foreground: string;
	mutedForeground: string;
	background: string;
	card: string;
	border: string;
	ring: string;
	forest: string;
	edge: string;
	series: string[];
	seq: string[];
	div: string[];
	noValue: string;
	fontUi: string;
	fontBody: string;
	fontHeading: string;
}

export function readTokens(el: Element = document.documentElement): Tokens {
	const cs = getComputedStyle(el);
	const v = (name: string) => cs.getPropertyValue(name).trim();
	return {
		foreground: v('--foreground'),
		mutedForeground: v('--muted-foreground'),
		background: v('--background'),
		card: v('--card'),
		border: v('--border'),
		ring: v('--ring'),
		forest: v('--forest'),
		edge: v('--chart-edge'),
		series: [1, 2, 3, 4].map((i) => v(`--chart-${i}`)),
		seq: [1, 2, 3, 4, 5].map((i) => v(`--seq-${i}`)),
		div: [1, 2, 3, 4, 5].map((i) => v(`--div-${i}`)),
		noValue: v('--no-value'),
		fontUi: v('--font-ui'),
		fontBody: v('--font-body'),
		fontHeading: v('--font-heading')
	};
}

/** Resolve a `var(--token)` color to its value; any other color passes through. */
export function resolveColor(color: string, el: Element = document.documentElement): string {
	const m = /^var\((--[\w-]+)\)$/.exec(color.trim());
	return m ? getComputedStyle(el).getPropertyValue(m[1]).trim() : color;
}
