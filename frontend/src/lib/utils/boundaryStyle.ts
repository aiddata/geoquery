/**
 * Per-FC styling helpers used by the map and the chip UI.
 *
 * Colors are the design system's four chart series (design-system.md §11),
 * returned as CSS variables so chips follow the theme; MapFrame resolves them
 * for MapLibre. Past four collections the colors repeat, and line width
 * (driven by group_level, so ADM0 is thicker than ADM2) and the chip labels
 * tell collections apart.
 */

const SERIES_COUNT = 4;

const DEFAULT_LINE_WIDTH = 1.5;

/** Pick a stable color for a given chip index: `var(--chart-1)` … `var(--chart-4)`, cycling. */
export function colorForIndex(index: number): string {
	// guard against negative or fractional indices
	const i = ((Math.floor(index) % SERIES_COUNT) + SERIES_COUNT) % SERIES_COUNT;
	return `var(--chart-${i + 1})`;
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
