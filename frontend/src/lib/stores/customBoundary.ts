import { writable } from 'svelte/store';
import type { FeatureCollection } from 'geojson';

export type OperationType = 'buffer' | 'simplify' | 'union';

export type Operation = {
	id: string;
	type: OperationType;
	params: Record<string, unknown>;
};

export type CustomBoundaryState = {
	/** Whether the custom boundary panel is active on the map page. */
	active: boolean;
	fileName: string;
	featureCount: number;
	originalFeatures: FeatureCollection | null;
	/** Ordered list of operations applied to originalFeatures to produce finalFeatures. */
	operations: Operation[];
	finalFeatures: FeatureCollection | null;
	saved: boolean;
};

const initial: CustomBoundaryState = {
	active: false,
	fileName: '',
	featureCount: 0,
	originalFeatures: null,
	operations: [],
	finalFeatures: null,
	saved: false,
};

function createCustomBoundaryStore() {
	const { subscribe, set, update } = writable<CustomBoundaryState>(initial);

	return {
		subscribe,
		activate: () => update((s) => ({ ...s, active: true })),
		deactivate: () => update((s) => ({ ...s, active: false })),
		setUpload: (fileName: string, features: FeatureCollection) =>
			update((s) => ({
				...s,
				fileName,
				featureCount: features.features.length,
				originalFeatures: features,
				finalFeatures: features,
				operations: [],
				saved: false,
			})),
		clearUpload: () =>
			update((s) => ({
				...s,
				fileName: '',
				featureCount: 0,
				originalFeatures: null,
				finalFeatures: null,
				operations: [],
				saved: false,
			})),
		reset: () => set(initial),
	};
}

export const customBoundary = createCustomBoundaryStore();