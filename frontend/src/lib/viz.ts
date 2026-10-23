import type { VizPayload } from '$lib/api';

// Shared utilities for the /viz/[id] and /viz/explore map renderers.

// YlGn and BrBG are the design system's `seq` and `div` ramps (design-system.md §3).
// RdYlGn is retired: its second and fourth steps merge under colorblind simulation.
export const DEFAULT_PALETTE = 'YlGn';

/** Missing values: `--no-value` (pewter), the same in both themes. Never a ramp step. */
export const NO_VALUE_COLOR = '#7b8985';

export const PALETTES: Record<string, { label: string; colors: string[] }> = {
	YlOrRd:  { label: 'Yellow → Orange → Red',  colors: ['#ffffb2','#fecc5c','#fd8d3c','#f03b20','#bd0026'] },
	Blues:   { label: 'Blues',                   colors: ['#eff3ff','#bdd7e7','#6baed6','#3182bd','#08519c'] },
	Greens:  { label: 'Greens',                  colors: ['#edf8e9','#bae4b3','#74c476','#31a354','#006d2c'] },
	Purples: { label: 'Purples',                 colors: ['#f2f0f7','#cbc9e2','#9e9ac8','#756bb1','#54278f'] },
	Oranges: { label: 'Oranges',                 colors: ['#feedde','#fdbe85','#fd8d3c','#e6550d','#a63603'] },
	YlGn:    { label: 'Yellow → Green',          colors: ['#ffffcc','#c2e699','#78c679','#31a354','#006837'] },
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
	const min = values.reduce((a, b) => (b < a ? b : a), values[0]);
	const max = values.reduce((a, b) => (b > a ? b : a), values[0]);
	const step = (max - min) / n;
	return Array.from({ length: n + 1 }, (_, i) => min + i * step);
}

export function getColor(value: unknown, breaks: number[], palette: string[]): string {
	if (value === null || value === undefined || isNaN(Number(value))) return NO_VALUE_COLOR;
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
	expr.push(NO_VALUE_COLOR);
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

// Human-readable field name: strips dataset prefix AND redundant type prefixes
// (categorical, binary, numeric, ordinal) that add noise without adding meaning.
export function fieldLabel(col: string): string {
	return prettyColumn(col)
		.replace(/_/g, ' ')
		.replace(/^(categorical|binary|numeric|ordinal)\s+/i, '');
}

export function escapeHtml(s: string): string {
	return s.replace(/[&<>"']/g, (c) => (
		{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!
	));
}

/**
 * A feature value as a number, or null when it's missing. `Number(null)` and `Number('')`
 * are 0, so a plain `isNaN(Number(v))` check would count missing values as zeros.
 */
export function numericValue(v: unknown): number | null {
	if (v === null || v === undefined || v === '' || typeof v === 'boolean') return null;
	const n = Number(v);
	return Number.isFinite(n) ? n : null;
}

/** The non-missing numeric values of one column across all features. */
export function columnValues(data: VizPayload, col: string): number[] {
	const out: number[] = [];
	for (const f of Object.values(data.features)) {
		const v = numericValue(f[col]);
		if (v !== null) out.push(v);
	}
	return out;
}

export function computeStats(values: number[]): { min: number; max: number; mean: number; n: number } {
	const min = values.reduce((a, b) => (b < a ? b : a), values[0]);
	const max = values.reduce((a, b) => (b > a ? b : a), values[0]);
	const mean = values.reduce((a, b) => a + b, 0) / values.length;
	return { min, max, mean, n: values.length };
}

// ── Chart helpers ─────────────────────────────────────────────────────────────

export interface TemporalSeriesEntry {
	col: string;
	temporal: string;
	values: number[];
	/** null when no feature has a value for this period */
	mean: number | null;
	min: number | null;
	max: number | null;
}

// col_groups is keyed by resource name (one per year, e.g. "esa_land_cover_2000").
// For time series we need to span across years, so we group instead by col_dataset_titles
// (the human-readable dataset name shared across all yearly resources).
export function getTemporalDatasets(data: VizPayload): Record<string, string[]> {
	const result: Record<string, string[]> = {};
	for (const col of data.columns) {
		if (!data.col_temporal[col]) continue;
		const title = data.col_dataset_titles[col] || col.split('.')[0];
		(result[title] ??= []).push(col);
	}
	return result;
}

// Field track: the category name within a dataset, stripped of type prefix.
// For a column like esa_land_cover_2000.categorical_bare_areas (temporal="2000"),
// the resource name already encodes the year, so prettyColumn gives "categorical_bare_areas"
// and we just strip the type prefix → "bare areas".
// For datasets where the year is embedded in the field name (e.g. worldpop.population_2000),
// prettyColumn gives "population_2000" and we strip "_2000" to get "population".
export function colFieldTrack(col: string, temporal: string): string {
	let raw = prettyColumn(col);
	const esc = temporal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	raw = raw.replace(new RegExp('[_.]?' + esc + '$'), '');
	return raw.replace(/_/g, ' ').replace(/^(categorical|binary|numeric|ordinal)\s+/i, '');
}

// Sorted list of distinct field tracks (categories) for a dataset title.
export function getDatasetFieldTracks(data: VizPayload, datasetTitle: string): string[] {
	const cols = getTemporalDatasets(data)[datasetTitle] ?? [];
	const tracks = new Set(cols.map(c => colFieldTrack(c, data.col_temporal[c])));
	return [...tracks].sort();
}

// datasetKey is now the dataset title (from col_dataset_titles), not the col_groups key.
// fieldTrack filters to one category within a multi-category dataset.
export function getTemporalSeries(data: VizPayload, datasetKey: string, fieldTrack?: string): TemporalSeriesEntry[] {
	const allCols = getTemporalDatasets(data)[datasetKey] ?? [];
	const cols = fieldTrack !== undefined
		? allCols.filter(c => colFieldTrack(c, data.col_temporal[c]) === fieldTrack)
		: allCols;
	return cols
		.map(col => {
			const vals = columnValues(data, col);
			const mean = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
			const min = vals.length ? vals.reduce((a, b) => Math.min(a, b), vals[0]) : null;
			const max = vals.length ? vals.reduce((a, b) => Math.max(a, b), vals[0]) : null;
			return { col, temporal: data.col_temporal[col], values: vals, mean, min, max };
		})
		.sort((a, b) => a.temporal.localeCompare(b.temporal));
}

export function detectBinary(values: number[]): boolean {
	return values.length > 0 && values.every(v => v === 0 || v === 1);
}

/** Pearson's r for paired values; NaN when it's undefined (fewer than two pairs, or no variance). */
export function pearsonCorrelation(xs: number[], ys: number[]): number {
	const n = Math.min(xs.length, ys.length);
	if (n < 2) return NaN;
	const mx = xs.slice(0, n).reduce((a, b) => a + b, 0) / n;
	const my = ys.slice(0, n).reduce((a, b) => a + b, 0) / n;
	let num = 0, dx2 = 0, dy2 = 0;
	for (let i = 0; i < n; i++) {
		const dx = xs[i] - mx, dy = ys[i] - my;
		num += dx * dy; dx2 += dx * dx; dy2 += dy * dy;
	}
	return dx2 > 0 && dy2 > 0 ? num / Math.sqrt(dx2 * dy2) : NaN;
}

/**
 * Correlation matrix over pairwise-complete features: each (i, j) cell uses only the
 * features that have a value in both columns, so pairs always come from the same feature.
 */
export function pearsonMatrix(data: VizPayload, cols: string[]): number[][] {
	const features = Object.values(data.features);
	const values = cols.map(col => features.map(f => numericValue(f[col])));
	return cols.map((_, i) => cols.map((_, j) => {
		const xs: number[] = [], ys: number[] = [];
		for (let k = 0; k < features.length; k++) {
			const x = values[i][k], y = values[j][k];
			if (x !== null && y !== null) { xs.push(x); ys.push(y); }
		}
		return pearsonCorrelation(xs, ys);
	}));
}
