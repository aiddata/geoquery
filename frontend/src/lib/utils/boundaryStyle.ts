/**
 * Per-FC styling helpers used by the map and the chip UI.
 *
 * Colors cycle through a fixed palette by index. Line width is driven by
 * group_level when available so coarser admin levels (ADM0) render with
 * thicker borders than finer ones (ADM2). Boundaries without a level
 * fall back to a neutral default that still composes with the cycling.
 */

const PALETTE = [
	'#2563eb', // blue
	'#d97706', // amber
	'#059669', // emerald
	'#7c3aed', // violet
	'#dc2626', // rose
	'#0891b2', // cyan
	'#65a30d', // lime
	'#c026d3', // fuchsia
] as const;

const DEFAULT_LINE_WIDTH = 1.5;

/** Pick a stable color for a given chip index, cycling through the palette. */
export function colorForIndex(index: number): string {
	const len = PALETTE.length;
	// guard against negative or fractional indices
	const i = ((Math.floor(index) % len) + len) % len;
	return PALETTE[i];
}

/**
 * Derive a line width from an admin level. ADM0 → thickest, ADM2 → thinnest.
 * Returns the default for anything outside the typical 0–3 range or for null.
 */
export function lineWidthForLevel(level: number | null | undefined): number {
	if (level === null || level === undefined) return DEFAULT_LINE_WIDTH;
	if (level < 0 || level > 4) return DEFAULT_LINE_WIDTH;
	// ADM0 → 2.5, ADM1 → 2.0, ADM2 → 1.5, ADM3 → 1.0, ADM4 → 0.75
	return Math.max(0.75, 4.5 - level * 0.5);
}
