import { writable, derived } from 'svelte/store';

// ── Types ────────────────────────────────────────────────────────────────────

export interface FCRef {
	id: number;
	name: string;
	title: string | null;
}

export interface SingleFCSelection {
	mode: 'single';
	fc: FCRef;
	featureIds: number[]; // Feature.id — empty means entire collection
	resolvedFeatureIds: number[]; // full flat list for requests/coverage (set on proceed)
}

export interface MultiFCSelection {
	mode: 'multi';
	fcs: FCRef[];
	resolvedFeatureIds: number[]; // full flat list for requests/coverage (set on proceed)
}

export type ActiveSelection = SingleFCSelection | MultiFCSelection | null;

// ── Store ────────────────────────────────────────────────────────────────────

function createSelectionStore() {
	const { subscribe, set, update } = writable<ActiveSelection>(null);

	return {
		subscribe,

		/** Start a single-FC selection. Clears any existing selection. */
		setSingleFC(fc: FCRef) {
			set({ mode: 'single', fc, featureIds: [], resolvedFeatureIds: [] });
		},

		/**
		 * Toggle a Feature.id within single-FC mode.
		 * No-op if not in single mode.
		 */
		toggleFeature(featureId: number) {
			update((sel) => {
				if (!sel || sel.mode !== 'single') return sel;
				const ids = sel.featureIds;
				return {
					...sel,
					featureIds: ids.includes(featureId)
						? ids.filter((id) => id !== featureId)
						: [...ids, featureId]
				};
			});
		},

		/** Reset the feature sub-selection to "entire collection". */
		clearFeatures() {
			update((sel) => {
				if (!sel || sel.mode !== 'single') return sel;
				return { ...sel, featureIds: [] };
			});
		},

		/**
		 * Add another FC.
		 * If currently in single mode, converts to multi (the existing FC is
		 * kept as a whole-collection entry and any feature sub-selection is dropped).
		 * If already in multi mode, appends the FC (no-op if already present).
		 */
		addFC(fc: FCRef) {
			update((sel) => {
				if (!sel) {
					return { mode: 'multi', fcs: [fc], resolvedFeatureIds: [] };
				}
				if (sel.mode === 'single') {
					// Convert to multi, carrying the existing single FC alongside the new one
					return { mode: 'multi', fcs: [sel.fc, fc], resolvedFeatureIds: [] };
				}
				// Already multi — skip if already present, otherwise append
				if (sel.fcs.some((f) => f.id === fc.id)) return sel;
				return { ...sel, fcs: [...sel.fcs, fc], resolvedFeatureIds: [] };
			});
		},

		/** Store the resolved flat Feature.id list for requests and coverage checks. */
		setResolvedFeatureIds(ids: number[]) {
			update((sel) => {
				if (!sel) return sel;
				return { ...sel, resolvedFeatureIds: ids };
			});
		},

		/** Remove an FC from multi mode. No-op if not in multi mode. */
		removeFC(fcId: number) {
			update((sel) => {
				if (!sel || sel.mode !== 'multi') return sel;
				const fcs = sel.fcs.filter((f) => f.id !== fcId);
				return fcs.length === 0 ? null : { ...sel, fcs };
			});
		},

		clear() {
			set(null);
		}
	};
}

export const selection = createSelectionStore();

// ── Derived helpers ──────────────────────────────────────────────────────────

/** FC IDs included in the current selection — used for dataset API calls. */
export const selectionFcIds = derived(selection, ($sel): number[] => {
	if (!$sel) return [];
	if ($sel.mode === 'single') return [$sel.fc.id];
	return $sel.fcs.map((fc) => fc.id);
});

/** FC names included in the current selection — used for tile display. */
export const selectionFcNames = derived(selection, ($sel): string[] => {
	if (!$sel) return [];
	if ($sel.mode === 'single') return [$sel.fc.name];
	return $sel.fcs.map((fc) => fc.name);
});

/**
 * The set of selected Feature.ids in single mode.
 * Empty array means the entire FC is selected.
 */
export const selectedFeatureIds = derived(selection, ($sel): number[] => {
	if (!$sel || $sel.mode !== 'single') return [];
	return $sel.featureIds;
});

/** Human-readable summary for the selection panel. */
export const selectionSummary = derived(selection, ($sel) => {
	if (!$sel) return null;
	if ($sel.mode === 'single') {
		const count = $sel.featureIds.length;
		return {
			label: $sel.fc.title ?? $sel.fc.name,
			detail: count === 0 ? 'All features' : `${count} feature${count === 1 ? '' : 's'} selected`
		};
	}
	return {
		label: `${$sel.fcs.length} boundary collection${$sel.fcs.length === 1 ? '' : 's'}`,
		detail: $sel.fcs.map((fc) => fc.title ?? fc.name).join(', ')
	};
});
