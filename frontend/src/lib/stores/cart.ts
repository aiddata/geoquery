import { writable, derived } from 'svelte/store';
import { mergeFeatureVersions } from '#lib/utils/featureMerge.js';

export interface RangeSelection {
	type: 'range';
	start: number;
	end: number;
}

export interface CategoricalSelection {
	type: 'categorical';
	selected: string[];
}

export type FilterSelection = RangeSelection | CategoricalSelection;

export interface CartItem {
	customName: string;
	datasetName: string;
	datasetTitle: string;
	datasetType: string;
	processingClass: string;
	// zonal_stats fields:
	extractTypes?: string[];
	resources?: string[];
	resourceLabels?: string[];
	// filter_and_agg fields:
	filterSelections?: Record<string, FilterSelection>;
	// generic per-task kwargs passed through to the backend processing function:
	kwargs?: Record<string, unknown>;
}

function createCartStore() {
	const { subscribe, update, set } = writable<CartItem[]>([]);

	return {
		subscribe,
		addItem(item: CartItem) {
			update((items) => [...items, item]);
		},
		/** Add item, or merge into the existing entry for the same dataset. */
		upsertItem(item: CartItem) {
			update((items) => {
				// Feature datasets: a version that matches an existing one apart from
				// one split field's values (e.g. years) merges into it, like a
				// raster's periods; anything else is a separate version.
				if (item.kwargs != null) {
					for (let idx = 0; idx < items.length; idx++) {
						const merged = mergeFeatureVersions(items[idx], item);
						if (merged) return items.map((it, i) => (i === idx ? merged : it));
					}
					return [...items, item];
				}

				const idx = items.findIndex((i) => i.datasetName === item.datasetName);
				if (idx === -1) return [...items, item];

				const existing = items[idx];
				const merged: CartItem = { ...existing };

				// Raster: union extractTypes
				if (item.extractTypes !== undefined) {
					const seen = new Set(existing.extractTypes ?? []);
					merged.extractTypes = [
						...(existing.extractTypes ?? []),
						...item.extractTypes.filter((t) => !seen.has(t))
					];
				}

				// Raster: union resources + keep resourceLabels in sync
				if (item.resources !== undefined) {
					const labelMap = new Map<string, string>();
					(existing.resources ?? []).forEach((r, i) =>
						labelMap.set(r, existing.resourceLabels?.[i] ?? r)
					);
					(item.resources ?? []).forEach((r, i) => {
						if (!labelMap.has(r)) labelMap.set(r, item.resourceLabels?.[i] ?? r);
					});
					merged.resources = [...labelMap.keys()];
					merged.resourceLabels = [...labelMap.values()];
				}

				return items.map((it, i) => (i === idx ? merged : it));
			});
		},
		/**
		 * Put a raster dataset's current options in the cart, replacing (not
		 * merging with) its existing entry. Rasters have one entry each, kept in
		 * step with the Customize page as options change.
		 */
		setRasterItem(item: CartItem) {
			update((items) => {
				const idx = items.findIndex((i) => i.datasetName === item.datasetName && i.kwargs == null);
				if (idx === -1) return [...items, item];
				return items.map((it, i) => (i === idx ? item : it));
			});
		},
		/** Remove a raster dataset's entry (the one without kwargs). */
		removeRasterItem(datasetName: string) {
			update((items) => items.filter((i) => !(i.datasetName === datasetName && i.kwargs == null)));
		},
		/**
		 * Replace one feature entry (found by its kwargs) with an edited version,
		 * in place: same position in the list, and the name the user gave it.
		 * Adds the item instead if that entry is gone.
		 */
		replaceFeatureItem(datasetName: string, oldKwargsKey: string, item: CartItem) {
			update((items) => {
				const idx = items.findIndex(
					(i) => i.datasetName === datasetName && JSON.stringify(i.kwargs ?? null) === oldKwargsKey
				);
				if (idx === -1) return [...items, item];
				let next: CartItem = { ...item, customName: items[idx].customName };
				// Fold in any other version the edit now matches (identical, or
				// differing only in one split field's values), so it doesn't leave
				// two versions with overlapping columns.
				const absorbed = new Set<number>();
				items.forEach((it, i) => {
					if (i === idx) return;
					const merged = mergeFeatureVersions(next, it);
					if (merged) {
						next = merged;
						absorbed.add(i);
					}
				});
				return items.map((it, i) => (i === idx ? next : it)).filter((_, i) => !absorbed.has(i));
			});
		},
		removeItem(index: number) {
			update((items) => items.filter((_, i) => i !== index));
		},
		updateItemName(index: number, name: string) {
			update((items) => items.map((item, i) => (i === index ? { ...item, customName: name } : item)));
		},
		setItems(items: CartItem[]) {
			set(items);
		},
		clear() {
			set([]);
		}
	};
}

export const cart = createCartStore();

export const cartCount = derived({ subscribe: cart.subscribe }, ($cart) => $cart.length);
