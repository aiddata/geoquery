import type { CartItem } from '#lib/stores/cart.js';

// Selected values are strings or numbers (years come through as numbers)
type Split = { type: 'categorical'; aggregate: false; selected: unknown[] };

const isSplit = (v: unknown): v is Split =>
	!!v && typeof v === 'object' && (v as Split).aggregate === false && (v as Split).type === 'categorical';

const isNumeric = (v: unknown) =>
	typeof v === 'number' || (typeof v === 'string' && v.trim() !== '' && !isNaN(Number(v)));

/** Union two selections; years (all numeric) end up in order, others keep first-seen order. */
function unionValues(a: unknown[], b: unknown[]): unknown[] {
	const out = [...a, ...b.filter((v) => !a.includes(v))];
	return out.every(isNumeric) ? out.sort((x, y) => Number(x) - Number(y)) : out;
}

/**
 * Merge feature-dataset version `incoming` into `existing`, the way a raster
 * entry merges its time periods, when the two differ only in the values
 * selected for one split field (e.g. years). Returns null when they can't be
 * merged: a different dataset, measure, filter, or more than one split field
 * differing (merging two split fields would add combinations neither asked for).
 *
 * The merged version keeps the existing one's name.
 */
export function mergeFeatureVersions(existing: CartItem, incoming: CartItem): CartItem | null {
	const a = existing.kwargs;
	const b = incoming.kwargs;
	if (!a || !b || existing.datasetName !== incoming.datasetName) return null;

	const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
	let differing: string | null = null;
	for (const key of keys) {
		if (JSON.stringify(a[key]) === JSON.stringify(b[key])) continue;
		if (differing !== null || !isSplit(a[key]) || !isSplit(b[key])) return null;
		differing = key;
	}
	if (differing === null) return existing; // identical: nothing to add

	const selected = unionValues((a[differing] as Split).selected, (b[differing] as Split).selected);
	return {
		...existing,
		kwargs: { ...a, [differing]: { ...(a[differing] as Split), selected } },
		filterSelections: existing.filterSelections && {
			...existing.filterSelections,
			// Typed string[], though years are numbers at runtime
			[differing]: { type: 'categorical', selected: selected as string[] }
		}
	};
}

/**
 * Whether feature options (their kwargs) would add nothing to `existing`:
 * identical to it, or a subset of it in one split field's values.
 */
export function versionCovers(existing: CartItem, kwargs: Record<string, unknown>): boolean {
	const merged = mergeFeatureVersions(existing, { ...existing, kwargs });
	if (!merged) return false;
	// Covered when the merge added no values (it may still have reordered them)
	return Object.entries(existing.kwargs ?? {}).every(([key, v]) => {
		if (!isSplit(v)) return true;
		return (merged.kwargs![key] as Split).selected.length === v.selected.length;
	});
}
