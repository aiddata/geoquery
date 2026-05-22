import { writable, derived } from 'svelte/store';

export interface CartItem {
	customName: string;
	datasetName: string;
	datasetTitle: string;
	datasetType: string;
	filters?: Record<string, string[]>;
	extractTypes?: string[];
	resources?: string[];
	resourceLabels?: string[];
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
