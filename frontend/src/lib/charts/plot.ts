// Observable Plot settings shared by every chart (design-system.md §9).
import type { Tokens } from '$lib/theme/tokens';

export type PlotModule = typeof import('@observablehq/plot');

let plotModule: Promise<PlotModule> | null = null;

/** Plot (and the d3 it imports) loads on first use, so pages without charts don't pay for it. */
export function loadPlot(): Promise<PlotModule> {
	plotModule ??= import('@observablehq/plot');
	return plotModule;
}

/** What a chart's draw function receives: Plot, the resolved tokens and the frame width. */
export interface DrawContext {
	Plot: PlotModule;
	t: Tokens;
	width: number;
}

export type DrawFn = (ctx: DrawContext) => SVGSVGElement | HTMLElement;

/** Settings every plot starts from (§9.3). */
export function aidBase(t: Tokens, width: number, height = 260) {
	return {
		width,
		height,
		style: {
			background: 'transparent',
			color: t.mutedForeground,
			fontFamily: t.fontUi,
			fontSize: '13px',
			fontWeight: '700',
			overflow: 'visible'
		}
	};
}

/** Tooltip box (§9.5). Use one tip mark per chart. */
export function aidTip(t: Tokens) {
	return { fill: t.card, stroke: t.axis, fontFamily: t.fontUi, fontSize: 13 };
}

/** Axis and label numbers: 2000 → "2K", 10400 → "10.4K". */
export const compact = new Intl.NumberFormat('en-US', {
	notation: 'compact',
	maximumFractionDigits: 1
}).format;

/** Tooltip and table numbers: full value with thousands separators. */
export function full(n: number | null | undefined, maximumFractionDigits = 3): string {
	if (n === null || n === undefined || !Number.isFinite(n)) return '—';
	return n.toLocaleString('en-US', { maximumFractionDigits });
}

export const MAX_SERIES = 4;

/** Pair with the first four series colors in point charts, so identity doesn't rest on color. */
export const SYMBOLS = ['circle', 'diamond', 'square', 'triangle'] as const;

/**
 * Keep at most four categories: past four, the first three keep their own color
 * and the rest fold into "Other" (§9.2).
 */
export function capCategories(names: string[], max = MAX_SERIES): { domain: string[]; of: (name: string) => string } {
	if (names.length <= max) return { domain: names, of: (n) => n };
	const kept = new Set(names.slice(0, max - 1));
	return { domain: [...kept, 'Other'], of: (n) => (kept.has(n) ? n : 'Other') };
}

/** A categorical color scale with an explicit domain, so a category keeps its color when others are filtered. */
export function seriesColor(t: Tokens, domain: string[], legend = domain.length > 1) {
	return { domain, range: t.series.slice(0, domain.length), legend };
}

/**
 * A domain widened to round numbers around [lo, hi], with explicit ticks on them (§9.3:
 * ticks are always given, so gridlines and labels land on the same values).
 */
export function niceScale(lo: number, hi: number, count = 5): { domain: [number, number]; ticks: number[] } {
	if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { domain: [0, 1], ticks: [0, 1] };
	if (lo === hi) {
		const pad = lo === 0 ? 1 : Math.abs(lo) * 0.1;
		return niceScale(lo - pad, hi + pad, count);
	}
	const step = niceStep((hi - lo) / count);
	const start = Math.floor(lo / step + 1e-9) * step;
	const end = Math.ceil(hi / step - 1e-9) * step;
	const ticks: number[] = [];
	for (let v = start; v <= end + step * 1e-9; v += step) ticks.push(Number(v.toPrecision(12)));
	return { domain: [start, end], ticks };
}

/** A tick formatter that suits the tick values: compact for large numbers, enough decimals for small ones. */
export function tickFormatFor(ticks: number[]): (n: number) => string {
	const step = ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) : Math.abs(ticks[0] ?? 1);
	if (step >= 1 && Math.max(...ticks.map(Math.abs)) >= 1000) return compact;
	const decimals = step >= 1 || step === 0 ? 0 : Math.min(6, Math.ceil(-Math.log10(step)));
	return (n) => n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function niceStep(raw: number): number {
	const exp = Math.floor(Math.log10(raw));
	const f = raw / 10 ** exp;
	const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
	return nice * 10 ** exp;
}

/** Band inset that caps bars at 24px thick (§9.4). */
export function barInset(bandSize: number, max = 24): number {
	return Math.max(0, (bandSize - max) / 2);
}

let measureCtx: CanvasRenderingContext2D | null = null;

/**
 * Width in px of the widest label in the chart-label face (Noto Sans 700 13px), so margins fit
 * their labels. Labels overflowing the SVG still show on the page but are clipped in exports.
 */
export function labelWidth(t: Tokens, labels: string[]): number {
	measureCtx ??= document.createElement('canvas').getContext('2d');
	if (!measureCtx) return Math.max(0, ...labels.map((l) => l.length * 8));
	measureCtx.font = `700 13px ${t.fontUi}`;
	return Math.max(0, ...labels.map((l) => measureCtx!.measureText(l).width));
}
