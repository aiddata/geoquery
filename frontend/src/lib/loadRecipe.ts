import { get, writable } from 'svelte/store';
import { applyRecipe, parseRecipe } from './recipe.js';
import { selection, customizeHref, type FCRef } from './stores/selection.js';
import { cart } from './stores/cart.js';
import { datasetChoices } from './stores/datasetChoices.js';
import { requestForm } from './stores/requestForm.js';
import { customBoundary } from './stores/customBoundary.js';
import type { RecipeDropped, RequestRecipeResult } from './api.js';

/**
 * Loading a recipe from somewhere else: a past request ("Use as template",
 * GEO-126) or a share link (/s/<id>). It replaces the request being built, so
 * callers confirm first when requestInProgress() says there's one, and it
 * says what was left out because it no longer applies.
 */

/** Shown on the steps after a recipe loads, until dismissed. */
export interface RecipeNotice {
	title: string;
	/** What was left out, one sentence each; empty when everything loaded. */
	dropped: string[];
}

export const recipeNotice = writable<RecipeNotice | null>(null);

/** Whether there's a request being built that loading a recipe would replace. */
export function requestInProgress(): boolean {
	const custom = get(customBoundary);
	return get(selection) !== null || get(cart).length > 0 || !!custom.finalFeatures;
}

const list = new Intl.ListFormat('en', { type: 'conjunction' });
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** What was dropped, as sentences for the notice. */
export function describeDropped(dropped: RecipeDropped, missingSets: number): string[] {
	const lines: string[] = [];
	if (missingSets > 0) {
		lines.push(`${plural(missingSets, 'boundary set')} ${missingSets === 1 ? "isn't" : "aren't"} available any more.`);
	}
	if (dropped.features > 0) {
		lines.push(`${plural(dropped.features, 'feature')} that ${dropped.features === 1 ? "wasn't" : "weren't"} part of a whole boundary set.`);
	}
	const titles = (reason: RecipeDropped['datasets'][number]['reason']) =>
		dropped.datasets.filter((d) => d.reason === reason).map((d) => d.title);
	const unavailable = titles('unavailable');
	const notCovered = titles('not_covered');
	const optionsRemoved = titles('options_removed');
	if (unavailable.length) lines.push(`No longer available: ${list.format(unavailable)}.`);
	if (notCovered.length) lines.push(`No data for these boundaries: ${list.format(notCovered)}.`);
	if (optionsRemoved.length) {
		lines.push(`None of the chosen measures or periods are available any more: ${list.format(optionsRemoved)}.`);
	}
	for (const o of dropped.options) {
		const parts = [
			o.periods.length ? `${plural(o.periods.length, 'period')} (${list.format(o.periods)})` : null,
			o.measures.length ? `${plural(o.measures.length, 'measure')} (${list.format(o.measures)})` : null
		].filter(Boolean);
		lines.push(`${o.title}: ${list.format(parts as string[])} no longer available.`);
	}
	return lines;
}

/**
 * Replace the request being built with a past request's recipe, and return
 * where to go next: Customize, or the map when none of its boundary sets
 * could be loaded.
 */
export function loadRequestTemplate(result: RequestRecipeResult, requestName: string): string {
	return loadRecipeResult(result, `Started from “${requestName}”`, "This request can't be used as a template.");
}

/** The same, for a share link. */
export function loadSharedRecipe(result: RequestRecipeResult): string {
	return loadRecipeResult(result, 'Opened a shared request', "This link can't be opened.");
}

function loadRecipeResult(result: RequestRecipeResult, title: string, invalid: string): string {
	const recipe = parseRecipe(result.recipe);
	if (!recipe) throw new Error(invalid);

	customBoundary.reset();
	datasetChoices.clearAll();
	requestForm.update((f) => ({ ...f, name: null, boundaryConsent: false }));
	const missing = applyRecipe(recipe, result.boundary_sets as FCRef[]);

	recipeNotice.set({
		title,
		dropped: describeDropped(result.dropped, missing.fcIds.length)
	});
	// Nothing selected (every boundary set gone): start again on the map
	if (!get(customizeHref)) return '/';
	// Boundaries only: back on the map with them selected, to pick datasets from
	// there. With datasets: Review, an overview of the whole request with a way
	// to change each part, whether it's to submit as is or to modify.
	return get(cart).length === 0 ? '/' : '/review';
}
