/**
 * Per-FC styling helpers used by the map and its selection legend.
 *
 * Colors are the design system's four chart series (design-system.md §11),
 * returned as CSS variables so the legend follows the theme; MapFrame resolves
 * them for MapLibre. Past four collections the colors repeat, and line width
 * (driven by group_level, so ADM0 is thicker than ADM2), the legend's labels
 * and its hover highlight tell collections apart.
 */

const SERIES_COUNT = 4;

const DEFAULT_LINE_WIDTH = 1.5;

/** The color for a slot (see assignColorSlots): `var(--chart-1)` … `var(--chart-4)`, cycling. */
export function colorForIndex(index: number): string {
	// guard against negative or fractional indices
	const i = ((Math.floor(index) % SERIES_COUNT) + SERIES_COUNT) % SERIES_COUNT;
	return `var(--chart-${i + 1})`;
}

/**
 * Give each selected boundary set a color slot that it keeps while it stays
 * selected, so removing one doesn't recolor the rest. Sets already in `prev`
 * keep their slot; sets no longer selected are dropped; each new set takes
 * the least-used slot (lowest index on a tie), so the four colors are used
 * once before any repeats.
 */
export function assignColorSlots(prev: ReadonlyMap<number, number>, ids: readonly number[]): Map<number, number> {
	const slots = new Map<number, number>();
	for (const id of ids) {
		const slot = prev.get(id);
		if (slot !== undefined) slots.set(id, slot);
	}
	const uses = Array<number>(SERIES_COUNT).fill(0);
	for (const slot of slots.values()) uses[slot]++;
	for (const id of ids) {
		if (slots.has(id)) continue;
		const slot = uses.indexOf(Math.min(...uses));
		slots.set(id, slot);
		uses[slot]++;
	}
	return slots;
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
