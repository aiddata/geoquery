import { writable, derived } from 'svelte/store';

export interface CartItem {
	customName: string;
	boundaryName: string;
	datasetName: string;
	datasetTitle: string;
	datasetType: string;
	filters?: Record<string, string[]>; // for release datasets
	extractTypes?: string[]; // for raster datasets
	resources?: string[]; // for raster temporal selections
	summary: string; // plain-text query description
}

function createCartStore() {
	const { subscribe, update, set } = writable<CartItem[]>([]);

	return {
		subscribe,
		addItem(item: CartItem) {
			update((items) => [...items, item]);
		},
		removeItem(index: number) {
			update((items) => items.filter((_, i) => i !== index));
		},
		updateItemName(index: number, name: string) {
			update((items) => items.map((item, i) => (i === index ? { ...item, customName: name } : item)));
		},
		clear() {
			set([]);
		}
	};
}

export const cart = createCartStore();

export const cartCount = derived({ subscribe: cart.subscribe }, ($cart) => $cart.length);
