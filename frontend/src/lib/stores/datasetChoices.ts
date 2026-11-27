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
 * - Feature (filter-and-aggregate) datasets: the selection being edited
 *   (GEO-153): its filters and outcome, the kwargs they produce, and which
 *   cart entry it is once complete (editingKey). Incomplete, it's only here.
 */
export interface DatasetChoices {
	rasterOptions?: { extractTypes: string[]; resources: string[] };
	filterSelections?: Record<string, FilterSelection>;
	selectedOutcome?: string;
	/** The kwargs the filters produce; compared against cart items' kwargs. */
	kwargs?: Record<string, unknown>;
	/**
	 * The kwargs key (JSON) of the cart entry these options are, kept in step
	 * as they change; unset while the selection is incomplete (not in the
	 * cart). Review's "Edit options" sets it to open that entry.
	 */
	editingKey?: string;
	/** An incomplete selection's name, kept from when it was in the cart */
	customName?: string;
	/**
	 * Something has been chosen in the feature selection being edited: a
	 * measure, a split value, or a filter narrowed. Unfinished and started,
	 * it's flagged in the dataset list and the panel's notice (GEO-168).
	 */
	started?: boolean;
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
		},
		/** Replace every dataset's choices, as when restoring a refreshed tab. */
		replaceAll(all: Record<string, DatasetChoices>) {
			set(structuredClone(all));
		}
	};
}

export const datasetChoices = createDatasetChoicesStore();
