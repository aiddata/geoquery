import { writable, derived } from 'svelte/store';

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
				const itemKwargs = JSON.stringify(item.kwargs ?? null);
				const hasKwargs = item.kwargs != null;

				// Items with kwargs are keyed by (datasetName + kwargs): different kwarg
				// combinations are independent cart slots; identical ones replace in place.
				if (hasKwargs) {
					const idx = items.findIndex(
						(i) => i.datasetName === item.datasetName &&
							JSON.stringify(i.kwargs ?? null) === itemKwargs
					);
					if (idx === -1) return [...items, item];
					return items.map((it, i) => (i === idx ? item : it));
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
