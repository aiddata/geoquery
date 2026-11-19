import { beforeEach, describe, expect, test } from 'bun:test';
import { get } from 'svelte/store';
import { describeDropped, loadRequestTemplate, loadSharedRecipe, recipeNotice, requestInProgress } from './loadRecipe';
import { selection, type FCRef } from './stores/selection';
import { cart, type CartItem } from './stores/cart';
import { datasetChoices } from './stores/datasetChoices';
import { requestForm } from './stores/requestForm';
import { customBoundary } from './stores/customBoundary';

const adm1: FCRef = { id: 11, name: 'gha_adm1', title: 'Ghana ADM1', short_name: null, bbox: null };
const adm2: FCRef = { id: 12, name: 'gha_adm2', title: 'Ghana ADM2', short_name: null, bbox: null };
const ntl: CartItem = {
	customName: 'Night lights', datasetName: 'ntl', datasetTitle: 'Night lights', datasetType: 'raster',
	processingClass: 'zonal_stats', extractTypes: ['mean'], resources: ['ntl_2020'], resourceLabels: ['2020']
};
const none = { features: 0, datasets: [], options: [] };

beforeEach(() => {
	selection.clear();
	cart.clear();
	datasetChoices.clearAll();
	customBoundary.reset();
	requestForm.set({ name: null, email: '', boundaryConsent: false });
	recipeNotice.set(null);
});

describe('requestInProgress', () => {
	test('is false with nothing chosen, true with boundaries or datasets', () => {
		expect(requestInProgress()).toBe(false);
		selection.replace([adm1]);
		expect(requestInProgress()).toBe(true);
		selection.clear();
		cart.setItems([ntl]);
		expect(requestInProgress()).toBe(true);
	});
});

describe('loadRequestTemplate', () => {
	test('replaces the request and goes to Customize', () => {
		selection.replace([adm2]);
		cart.setItems([{ ...ntl, datasetName: 'old' }]);
		datasetChoices.save('old', { rasterOptions: { extractTypes: [], resources: ['x'] } });
		requestForm.update((f) => ({ ...f, name: 'Old name', email: 'a@example.org' }));

		const href = loadRequestTemplate(
			{ recipe: { v: 1, boundaries: { fcIds: [11, 12], featureIds: [] }, datasets: [ntl] }, boundary_sets: [adm1, adm2], dropped: none },
			'Ghana lights'
		);
		expect(href).toBe('/customize');
		expect(get(selection)).toMatchObject({ mode: 'multi', fcs: [adm1, adm2] });
		expect(get(cart)).toEqual([ntl]);
		expect(get(datasetChoices)).toEqual({});
		// A fresh name; the email stays
		expect(get(requestForm)).toMatchObject({ name: null, email: 'a@example.org' });
		expect(get(recipeNotice)).toEqual({ title: 'Started from “Ghana lights”', dropped: [] });
	});

	test('goes to the map when none of its boundary sets are available', () => {
		const href = loadRequestTemplate(
			{ recipe: { v: 1, boundaries: { fcIds: [99], featureIds: [] }, datasets: [ntl] }, boundary_sets: [], dropped: none },
			'Gone'
		);
		expect(href).toBe('/');
		expect(get(recipeNotice)?.dropped).toEqual(["1 boundary set isn't available any more."]);
	});

	test('a share link loads the same way, keeping names given on Review', () => {
		const renamed = { ...ntl, customName: 'Lights at night' };
		const href = loadSharedRecipe({
			recipe: { v: 1, boundaries: { fcIds: [12], featureIds: [3, 4] }, datasets: [renamed] },
			boundary_sets: [adm2],
			dropped: none
		});
		expect(href).toBe('/customize');
		expect(get(selection)).toMatchObject({ mode: 'single', featureIds: [3, 4] });
		expect(get(cart)).toEqual([renamed]);
		expect(get(recipeNotice)?.title).toBe('Opened a shared request');
	});

	test('rejects a recipe it does not recognise', () => {
		expect(() => loadRequestTemplate({ recipe: { v: 9 }, boundary_sets: [], dropped: none }, 'x')).toThrow();
		expect(get(selection)).toBeNull();
	});
});

describe('describeDropped', () => {
	test('says what was left out, grouped', () => {
		expect(
			describeDropped(
				{
					features: 3,
					datasets: [
						{ name: 'a', title: 'A', reason: 'unavailable' },
						{ name: 'b', title: 'B', reason: 'unavailable' },
						{ name: 'c', title: 'C', reason: 'not_covered' },
						{ name: 'd', title: 'D', reason: 'options_removed' }
					],
					options: [{ name: 'e', title: 'E', measures: ['median'], periods: ['1999', '2000'] }]
				},
				2
			)
		).toEqual([
			"2 boundary sets aren't available any more.",
			"3 features that weren't part of a whole boundary set.",
			'No longer available: A and B.',
			'No data for these boundaries: C.',
			'None of the chosen measures or periods are available any more: D.',
			'E: 2 periods (1999 and 2000) and 1 measure (median) no longer available.'
		]);
	});

	test('is empty when everything loaded', () => {
		expect(describeDropped(none, 0)).toEqual([]);
	});
});
