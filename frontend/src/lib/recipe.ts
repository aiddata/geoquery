import { get } from 'svelte/store';
import { selection, type FCRef } from './stores/selection.js';
import { cart, type CartItem } from './stores/cart.js';

/**
 * A request recipe (GEO-126): everything needed to rebuild a request's
 * boundaries and datasets, without its name or email. Versioned, so stored
 * recipes keep loading when the format changes.
 *
 * Restoring a tab after a refresh uses it now; share links and "Use as
 * template" on past requests are to use the same format and loader.
 * Custom uploads aren't part of a recipe.
 */
export interface RequestRecipe {
	v: 1;
	boundaries: {
		/** Boundary set (FeatureCollection) ids, in the order they were picked. */
		fcIds: number[];
		/** Features of a single boundary set; empty means the whole set. */
		featureIds: number[];
	};
	/** The datasets and their options, as the cart holds them. */
	datasets: CartItem[];
}

export const RECIPE_VERSION = 1;

const isIdList = (v: unknown): v is number[] =>
	Array.isArray(v) && v.every((n) => Number.isInteger(n) && n > 0);

const isCartItem = (v: unknown): v is CartItem => {
	if (!v || typeof v !== 'object') return false;
	const item = v as Record<string, unknown>;
	return (
		typeof item.datasetName === 'string' &&
		typeof item.customName === 'string' &&
		typeof item.processingClass === 'string'
	);
};

/** The recipe for the request being built, or null when nothing is selected. */
export function currentRecipe(): RequestRecipe | null {
	const sel = get(selection);
	const datasets = get(cart);
	if (!sel && datasets.length === 0) return null;
	const fcIds = !sel ? [] : sel.mode === 'single' ? [sel.fc.id] : sel.fcs.map((fc) => fc.id);
	const featureIds = sel?.mode === 'single' ? [...sel.featureIds] : [];
	return { v: RECIPE_VERSION, boundaries: { fcIds, featureIds }, datasets: structuredClone(datasets) };
}

/**
 * A recipe from storage or the network, checked: null if it isn't one, or is
 * a version this code doesn't know. Datasets that aren't well formed are
 * dropped rather than failing the whole recipe.
 */
export function parseRecipe(value: unknown): RequestRecipe | null {
	if (!value || typeof value !== 'object') return null;
	const r = value as Record<string, unknown>;
	if (r.v !== RECIPE_VERSION) return null;
	const b = r.boundaries as Record<string, unknown> | undefined;
	if (!b || !isIdList(b.fcIds) || !isIdList(b.featureIds)) return null;
	if (!Array.isArray(r.datasets)) return null;
	return {
		v: RECIPE_VERSION,
		boundaries: { fcIds: [...b.fcIds], featureIds: b.fcIds.length === 1 ? [...b.featureIds] : [] },
		datasets: r.datasets.filter(isCartItem)
	};
}

/** What a recipe asked for that couldn't be applied. */
export interface RecipeDropped {
	/** Boundary set ids with no matching boundary set. */
	fcIds: number[];
}

/**
 * Apply a recipe to the selection and cart, replacing what's there. `fcs` are
 * the boundary sets the recipe names, as far as they could be found; any it
 * names that are missing are reported. The Customize page then drops any
 * dataset the boundaries don't cover, as it does for every selection.
 */
export function applyRecipe(recipe: RequestRecipe, fcs: FCRef[]): RecipeDropped {
	const byId = new Map(fcs.map((fc) => [fc.id, fc]));
	const found = recipe.boundaries.fcIds.map((id) => byId.get(id)).filter((fc): fc is FCRef => !!fc);
	// A feature sub-selection only means something for the one set it was made in
	const featureIds = found.length === 1 && recipe.boundaries.fcIds.length === 1 ? recipe.boundaries.featureIds : [];
	selection.replace(found, featureIds);
	cart.setItems(structuredClone(recipe.datasets));
	return { fcIds: recipe.boundaries.fcIds.filter((id) => !byId.has(id)) };
}
