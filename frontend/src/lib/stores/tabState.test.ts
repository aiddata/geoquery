import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { get } from 'svelte/store';
import { persistTabState, restoreTabState } from './tabState';
import { selection, type FCRef } from './selection';
import { cart, type CartItem } from './cart';
import { datasetChoices } from './datasetChoices';
import { requestForm } from './requestForm';
import { customBoundary } from './customBoundary';

const KEY = 'geoquery-working-request';

// A sessionStorage and window for bun's test runner
class MemoryStorage {
	data = new Map<string, string>();
	getItem = (k: string) => this.data.get(k) ?? null;
	setItem = (k: string, v: string) => void this.data.set(k, v);
	removeItem = (k: string) => void this.data.delete(k);
}
let storage: MemoryStorage;
const listeners = new Map<string, () => void>();
(globalThis as any).window = {
	get sessionStorage() {
		return storage;
	},
	addEventListener: (type: string, fn: () => void) => listeners.set(type, fn),
	removeEventListener: (type: string) => listeners.delete(type)
};

const ghana2: FCRef = { id: 12, name: 'gb_gha_adm2', title: 'Ghana ADM2', short_name: null, bbox: [-3, 4, 1, 11] };
const ntl: CartItem = {
	customName: 'Night lights',
	datasetName: 'viirs_ntl',
	datasetTitle: 'VIIRS Night Lights',
	datasetType: 'raster',
	processingClass: 'zonal_stats',
	extractTypes: ['mean'],
	resources: ['2020'],
	resourceLabels: ['2020']
};

function resetStores() {
	selection.clear();
	cart.clear();
	datasetChoices.clearAll();
	requestForm.set({ name: null, email: '', boundaryConsent: false });
	customBoundary.reset();
}

let stop: () => void;
beforeEach(() => {
	storage = new MemoryStorage();
	resetStores();
	stop = persistTabState();
});
afterEach(() => stop());

/** Save now (as when the page is hidden) instead of waiting for the batch. */
const flush = () => listeners.get('pagehide')?.();

describe('tab state', () => {
	test('survives a refresh: selection, cart, choices and form', () => {
		selection.replace([ghana2], [5, 7]);
		cart.setItems([ntl]);
		datasetChoices.save('dmsp_ntl', { rasterOptions: { extractTypes: [], resources: ['1999'] } });
		requestForm.update((f) => ({ ...f, name: 'Ghana lights', email: 'a@example.org' }));
		flush();

		// The refresh: stores start empty, then the saved state is put back
		stop();
		resetStores();
		restoreTabState();

		expect(get(selection)).toEqual({ mode: 'single', fc: ghana2, featureIds: [5, 7], resolvedFeatureIds: [5, 7] });
		expect(get(cart)).toEqual([ntl]);
		expect(datasetChoices.get('dmsp_ntl')).toEqual({ rasterOptions: { extractTypes: [], resources: ['1999'] } });
		expect(get(requestForm)).toMatchObject({ name: 'Ghana lights', email: 'a@example.org' });
	});

	test('a multi-set selection comes back with its resolved features to be fetched again', () => {
		const ghana1: FCRef = { id: 11, name: 'gb_gha_adm1', title: 'Ghana ADM1', short_name: null };
		selection.replace([ghana1, ghana2]);
		selection.setResolvedFeatureIds([1, 2, 3]);
		flush();
		stop();
		resetStores();
		restoreTabState();
		expect(get(selection)).toEqual({ mode: 'multi', fcs: [ghana1, ghana2], resolvedFeatureIds: [] });
	});

	test('nothing is kept once the request is cleared, as after a submit', () => {
		selection.replace([ghana2]);
		cart.setItems([ntl]);
		flush();
		expect(storage.getItem(KEY)).not.toBeNull();
		cart.clear();
		selection.clear();
		flush();
		expect(storage.getItem(KEY)).toBeNull();
	});

	test('nothing is kept while a custom upload is in use', () => {
		selection.replace([ghana2]);
		flush();
		customBoundary.activate();
		flush();
		expect(storage.getItem(KEY)).toBeNull();
	});

	test('saved state it does not recognise is discarded', () => {
		stop();
		storage.setItem(KEY, '{"v":7}');
		restoreTabState();
		expect(get(selection)).toBeNull();
		expect(storage.getItem(KEY)).toBeNull();
		storage.setItem(KEY, 'not json');
		restoreTabState();
		expect(storage.getItem(KEY)).toBeNull();
	});
});
