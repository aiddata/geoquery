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
