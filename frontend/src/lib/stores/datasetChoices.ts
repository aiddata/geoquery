import { get, writable } from 'svelte/store';
import type { FilterSelection } from './cart.js';

/**
 * The options chosen for each dataset on the Customize page, keyed by dataset
 * name. A module-level store, so choices survive moving between pages of the
 * app (Customize → Review → back), like the cart they feed.
 *
 * - Raster datasets: the cart is the source of truth once options are valid
 *   (customize writes them straight into it); this only holds choices that
 *   aren't valid yet, such as time periods with no statistic.
 * - Feature (filter-and-aggregate) datasets: the current filters and outcome,
 *   with the kwargs they produce, so Customize can tell whether they match a
 *   cart entry (saved) or not (unsaved).
 */
export interface DatasetChoices {
	rasterOptions?: { extractTypes: string[]; resources: string[] };
	filterSelections?: Record<string, FilterSelection>;
	selectedOutcome?: string;
	/** The kwargs the filters produce; compared against cart items' kwargs. */
	kwargs?: Record<string, unknown>;
	/**
	 * Set when the dataset was opened with the Review page's "Edit options":
	 * the kwargs key (JSON) of the cart entry being edited, which Update
	 * Request replaces.
	 */
	editingKey?: string;
}

function createDatasetChoicesStore() {
	const store = writable<Record<string, DatasetChoices>>({});
	const { subscribe, update, set } = store;

	return {
		subscribe,
		get(name: string): DatasetChoices | undefined {
			return get(store)[name];
		},
		save(name: string, choices: DatasetChoices) {
			update((all) => ({ ...all, [name]: structuredClone(choices) }));
		},
		clear(name: string) {
			update((all) => {
				const rest = { ...all };
				delete rest[name];
				return rest;
			});
		},
		clearAll() {
			set({});
		}
	};
}

export const datasetChoices = createDatasetChoicesStore();
