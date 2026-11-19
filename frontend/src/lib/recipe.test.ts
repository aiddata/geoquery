import { beforeEach, describe, expect, test } from 'bun:test';
import { get } from 'svelte/store';
import { applyRecipe, currentRecipe, parseRecipe } from './recipe';
import { selection, type FCRef } from './stores/selection';
import { cart, type CartItem } from './stores/cart';

const ghana1: FCRef = { id: 11, name: 'gb_gha_adm1', title: 'Ghana ADM1', short_name: null, bbox: null };
const ghana2: FCRef = { id: 12, name: 'gb_gha_adm2', title: 'Ghana ADM2', short_name: null, bbox: null };
const ntl: CartItem = {
	customName: 'Night lights',
	datasetName: 'viirs_ntl',
	datasetTitle: 'VIIRS Night Lights',
	datasetType: 'raster',
	processingClass: 'zonal_stats',
	extractTypes: ['mean'],
	resources: ['2020', '2021'],
	resourceLabels: ['2020', '2021']
};

beforeEach(() => {
	selection.clear();
	cart.clear();
});

describe('currentRecipe', () => {
	test('is null with nothing selected', () => {
		expect(currentRecipe()).toBeNull();
	});

	test('records a single set with its features, and the cart', () => {
		selection.replace([ghana2], [5, 7]);
		cart.setItems([ntl]);
		expect(currentRecipe()).toEqual({
			v: 1,
			boundaries: { fcIds: [12], featureIds: [5, 7] },
			datasets: [ntl]
		});
	});

	test('records several sets in order, with no features', () => {
		selection.replace([ghana2, ghana1]);
		expect(currentRecipe()?.boundaries).toEqual({ fcIds: [12, 11], featureIds: [] });
	});
});

describe('parseRecipe', () => {
	test('round-trips a recipe through JSON', () => {
		selection.replace([ghana2], [5]);
		cart.setItems([ntl]);
		const recipe = currentRecipe();
		expect(parseRecipe(JSON.parse(JSON.stringify(recipe)))).toEqual(recipe);
	});

	test('rejects unknown versions and malformed boundaries', () => {
		expect(parseRecipe(null)).toBeNull();
		expect(parseRecipe({ v: 2, boundaries: { fcIds: [], featureIds: [] }, datasets: [] })).toBeNull();
		expect(parseRecipe({ v: 1, boundaries: { fcIds: ['x'], featureIds: [] }, datasets: [] })).toBeNull();
		expect(parseRecipe({ v: 1, boundaries: { fcIds: [1] }, datasets: [] })).toBeNull();
	});

	test('drops malformed datasets, and features when there are several sets', () => {
		const parsed = parseRecipe({
			v: 1,
			boundaries: { fcIds: [11, 12], featureIds: [5] },
			datasets: [ntl, { datasetName: 3 }, 'junk']
		});
		expect(parsed).toEqual({ v: 1, boundaries: { fcIds: [11, 12], featureIds: [] }, datasets: [ntl] });
	});
});

describe('applyRecipe', () => {
	test('replaces the selection and cart', () => {
		selection.replace([ghana1]);
		cart.setItems([{ ...ntl, datasetName: 'other' }]);
		const dropped = applyRecipe({ v: 1, boundaries: { fcIds: [12], featureIds: [5] }, datasets: [ntl] }, [ghana2]);
		expect(dropped).toEqual({ fcIds: [] });
		expect(get(selection)).toEqual({ mode: 'single', fc: ghana2, featureIds: [5], resolvedFeatureIds: [5] });
		expect(get(cart)).toEqual([ntl]);
	});

	test('reports boundary sets it could not find, and keeps the rest', () => {
		const dropped = applyRecipe({ v: 1, boundaries: { fcIds: [11, 99], featureIds: [] }, datasets: [] }, [ghana1]);
		expect(dropped).toEqual({ fcIds: [99] });
		expect(get(selection)).toMatchObject({ mode: 'single', fc: ghana1, featureIds: [] });
	});

	test('clears the selection when no set is found', () => {
		selection.replace([ghana1]);
		applyRecipe({ v: 1, boundaries: { fcIds: [99], featureIds: [] }, datasets: [] }, []);
		expect(get(selection)).toBeNull();
	});
});
