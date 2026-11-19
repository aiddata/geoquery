import { get } from 'svelte/store';
import { selection, type FCRef } from './selection.js';
import { cart } from './cart.js';
import { datasetChoices, type DatasetChoices } from './datasetChoices.js';
import { requestForm } from './requestForm.js';
import { customBoundary } from './customBoundary.js';
import { applyRecipe, currentRecipe, parseRecipe, type RequestRecipe } from '../recipe.js';

/**
 * The request being built survives a refresh of its tab (GEO-126): saved to
 * sessionStorage on every change, restored when the app loads. Nothing goes to
 * the server, it works signed out, two tabs keep separate requests, and closing
 * the tab ends it. Keeping a request any longer is what share links are for.
 *
 * Not kept: custom uploads (their geometry can be too large to store here).
 * While one is in use nothing is saved, so a refresh starts afresh.
 */
const STORAGE_KEY = 'geoquery-working-request';

interface TabState {
	v: 1;
	recipe: RequestRecipe;
	/** The selected boundary sets' names and extents, so nothing need be fetched to restore them. */
	fcs: FCRef[];
	/** Customize options not yet in the cart, and feature datasets' filters. */
	choices: Record<string, DatasetChoices>;
	form: { name: string | null; email: string };
}

function storage(): Storage | null {
	try {
		return window.sessionStorage;
	} catch {
		return null;
	}
}

const isFcRef = (v: unknown): v is FCRef =>
	!!v && typeof v === 'object' && Number.isInteger((v as FCRef).id) && typeof (v as FCRef).name === 'string';

/** Put back the request saved for this tab, if any. Call before the pages set up. */
export function restoreTabState() {
	const store = storage();
	const raw = store?.getItem(STORAGE_KEY);
	if (!raw) return;
	try {
		const state = JSON.parse(raw) as Partial<TabState>;
		const recipe = parseRecipe(state.recipe);
		if (state.v !== 1 || !recipe) throw new Error('unrecognised');
		applyRecipe(recipe, Array.isArray(state.fcs) ? state.fcs.filter(isFcRef) : []);
		if (state.choices && typeof state.choices === 'object') datasetChoices.replaceAll(state.choices);
		const form = state.form;
		if (form) {
			requestForm.update((f) => ({
				...f,
				name: typeof form.name === 'string' ? form.name : null,
				email: typeof form.email === 'string' ? form.email : ''
			}));
		}
	} catch {
		store?.removeItem(STORAGE_KEY);
	}
}

function snapshot(): TabState | null {
	if (get(customBoundary).active) return null;
	const recipe = currentRecipe();
	const choices = get(datasetChoices);
	const { name, email } = get(requestForm);
	if (!recipe && Object.keys(choices).length === 0) return null;
	const sel = get(selection);
	const fcs = !sel ? [] : sel.mode === 'single' ? [sel.fc] : sel.fcs;
	return {
		v: 1,
		recipe: recipe ?? { v: 1, boundaries: { fcIds: [], featureIds: [] }, datasets: [] },
		fcs,
		choices,
		form: { name, email }
	};
}

/**
 * Save the request on every change (batched, and flushed when the page is
 * hidden or unloaded). Returns a function that stops saving.
 */
export function persistTabState(): () => void {
	const store = storage();
	if (!store) return () => {};

	let timer: ReturnType<typeof setTimeout> | undefined;
	const write = () => {
		clearTimeout(timer);
		timer = undefined;
		const state = snapshot();
		try {
			if (state) store.setItem(STORAGE_KEY, JSON.stringify(state));
			else store.removeItem(STORAGE_KEY);
		} catch {
			// Full or blocked: the request just won't survive a refresh
		}
	};
	const schedule = () => {
		clearTimeout(timer);
		timer = setTimeout(write, 250);
	};
	const flush = () => {
		if (timer !== undefined) write();
	};

	const stops = [selection, cart, datasetChoices, requestForm, customBoundary].map((s) => s.subscribe(schedule));
	window.addEventListener('pagehide', flush);
	return () => {
		flush();
		stops.forEach((stop) => stop());
		window.removeEventListener('pagehide', flush);
	};
}
