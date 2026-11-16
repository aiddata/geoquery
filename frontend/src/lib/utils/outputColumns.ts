import type { CartItem } from '#lib/stores/cart.js';

/**
 * Columns one request entry adds to the output for each feature.
 *
 * - Rasters: one per statistic per time period (one period when the dataset
 *   has none). A categorical statistic really adds one per category, which
 *   the entry doesn't record, so it counts as one here.
 * - Feature datasets: the product of the values selected in each split
 *   (aggregate: false) field; filter fields only narrow the records.
 */
export function entryColumns(item: CartItem): number {
	if (item.kwargs) {
		let columns = 1;
		for (const value of Object.values(item.kwargs)) {
			const f = value as { type?: string; aggregate?: boolean; selected?: unknown[] } | null;
			if (f && typeof f === 'object' && f.aggregate === false && f.type === 'categorical') {
				columns *= f.selected?.length ?? 0;
			}
		}
		return columns;
	}
	return (item.extractTypes?.length ?? 0) * Math.max(1, item.resources?.length ?? 0);
}

/** Total columns per dataset across all its entries in the request. */
export function columnsByDataset(items: CartItem[]): Map<string, number> {
	const totals = new Map<string, number>();
	for (const item of items) {
		totals.set(item.datasetName, (totals.get(item.datasetName) ?? 0) + entryColumns(item));
	}
	return totals;
}

/** Display names of the filter (aggregate) fields a selection narrows. */
export function narrowedFilters(
	filters: Record<string, import('#lib/api.js').DatasetFilter> | null,
	selections: Record<string, import('#lib/stores/cart.js').FilterSelection> | undefined
): string[] {
	const names: string[] = [];
	for (const [key, f] of Object.entries(filters ?? {})) {
		if (f.aggregate === false) continue;
		const sel = selections?.[key];
		const narrowed =
			(f.type === 'categorical' && sel?.type === 'categorical' && sel.selected.length < f.categories.length) ||
			(f.type === 'range' && sel?.type === 'range' && (sel.start > f.min || sel.end < f.max));
		if (narrowed) names.push(f.display ?? key);
	}
	return names;
}

/**
 * A feature-dataset version's name, which prefixes its output columns: spaces
 * become underscores and anything but letters, digits and underscores is
 * dropped (the backend applies the same rule).
 */
export function cleanVersionName(name: string): string {
	return name.replace(/ /g, '_').replace(/[^A-Za-z0-9_]/g, '');
}

/** `base`, or `base_2`, `base_3`… if another feature entry already has it (case-insensitive). */
export function uniqueVersionName(base: string, items: CartItem[]): string {
	const taken = new Set(items.filter((i) => i.kwargs).map((i) => i.customName.toLowerCase()));
	let name = base;
	for (let n = 2; taken.has(name.toLowerCase()); n++) name = `${base}_${n}`;
	return name;
}

/** Indexes of feature entries whose name is empty or used by another feature entry. */
export function invalidVersionNames(items: CartItem[]): Set<number> {
	const bad = new Set<number>();
	const seen = new Map<string, number>();
	items.forEach((item, i) => {
		if (!item.kwargs) return;
		const key = item.customName.toLowerCase();
		if (!key) bad.add(i);
		else if (seen.has(key)) { bad.add(i); bad.add(seen.get(key)!); }
		else seen.set(key, i);
	});
	return bad;
}
