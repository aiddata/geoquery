// Shared utilities for the /viz/[id] and /viz/explore map renderers.

export const PALETTES: Record<string, { label: string; colors: string[] }> = {
	YlOrRd:  { label: 'Yellow → Orange → Red',  colors: ['#ffffb2','#fecc5c','#fd8d3c','#f03b20','#bd0026'] },
	Blues:   { label: 'Blues',                   colors: ['#eff3ff','#bdd7e7','#6baed6','#3182bd','#08519c'] },
	Greens:  { label: 'Greens',                  colors: ['#edf8e9','#bae4b3','#74c476','#31a354','#006d2c'] },
	Purples: { label: 'Purples',                 colors: ['#f2f0f7','#cbc9e2','#9e9ac8','#756bb1','#54278f'] },
	Oranges: { label: 'Oranges',                 colors: ['#feedde','#fdbe85','#fd8d3c','#e6550d','#a63603'] },
	YlGn:    { label: 'Yellow → Green',          colors: ['#ffffcc','#c2e699','#78c679','#31a354','#006837'] },
	RdYlGn:  { label: 'Red → Yellow → Green ↔', colors: ['#d7191c','#fdae61','#ffffbf','#a6d96a','#1a9641'] },
	RdBu:    { label: 'Red → Blue ↔',           colors: ['#ca0020','#f4a582','#f7f7f7','#92c5de','#0571b0'] },
	PuOr:    { label: 'Purple → Orange ↔',      colors: ['#5e3696','#b2abd2','#f7f7f7','#fdb863','#e66101'] },
	BrBG:    { label: 'Brown → Blue-Green ↔',   colors: ['#8c510a','#d8b365','#f5f5f5','#5ab4ac','#01665e'] },
};

export function quantileBreaks(values: number[], n: number): number[] {
	const sorted = [...values].sort((a, b) => a - b);
	if (sorted[0] === sorted[sorted.length - 1]) {
		return Array.from({ length: n + 1 }, () => sorted[0]);
	}
	const breaks = [sorted[0]];
	for (let i = 1; i <= n; i++) {
		breaks.push(sorted[Math.round((i / n) * (sorted.length - 1))]);
	}
	return breaks;
}

export function equalBreaks(values: number[], n: number): number[] {
	const min = Math.min(...values), max = Math.max(...values);
	const step = (max - min) / n;
	return Array.from({ length: n + 1 }, (_, i) => min + i * step);
}

export function getColor(value: unknown, breaks: number[], palette: string[]): string {
	if (value === null || value === undefined || isNaN(Number(value))) return '#cbd5e1';
	const v = Number(value);
	for (let i = 1; i < breaks.length; i++) {
		if (v <= breaks[i]) return palette[i - 1];
	}
	return palette[palette.length - 1];
}

export type FeatureRecord = { name: string; fc: string; [k: string]: unknown };

export function buildColorExpression(
	fc: string,
	column: string,
	breaks: number[],
	palette: string[],
	features: Record<string, FeatureRecord>,
	overrides?: Record<string, number | null>,
): unknown[] {
	const expr: unknown[] = ['match', ['get', 'id']];
	for (const [idStr, feat] of Object.entries(features)) {
		if (feat.fc !== fc) continue;
		const val = overrides ? (overrides[idStr] ?? null) : feat[column];
		expr.push(parseInt(idStr), getColor(val, breaks, palette));
	}
	expr.push('#cbd5e1');
	return expr;
}

export function fmt(n: number | null | undefined): string {
	if (n === null || n === undefined || !isFinite(n)) return '—';
	const abs = Math.abs(n);
	if (abs >= 10000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
	if (abs >= 100) return n.toFixed(1);
	if (abs >= 1) return n.toFixed(3);
	if (n === 0) return '0';
	return n.toPrecision(3);
}

export function prettyColumn(col: string): string {
	const parts = col.split('.');
	return parts.length > 1 ? parts.slice(1).join('.') : col;
}

export function escapeHtml(s: string): string {
	return s.replace(/[&<>"']/g, (c) => (
		{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!
	));
}

export function computeStats(values: number[]): { min: number; max: number; mean: number; n: number } {
	const min = Math.min(...values);
	const max = Math.max(...values);
	const mean = values.reduce((a, b) => a + b, 0) / values.length;
	return { min, max, mean, n: values.length };
}
