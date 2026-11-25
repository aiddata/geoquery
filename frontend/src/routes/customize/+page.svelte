<script lang="ts">
	import Seo from '#lib/components/layout/Seo.svelte';
	import { get } from 'svelte/store';
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { currentStep } from '#lib/stores/ui.js';
	import DetailBack from '#lib/components/layout/DetailBack.svelte';
	import { openDetail } from '#lib/stepDetail.js';
	import { cart, cartCount, type CartItem } from '#lib/stores/cart.js';
	import { datasetChoices } from '#lib/stores/datasetChoices.js';
	import {
		selection,
		selectionFcIds,
		selectedFeatureIds,
		type FCRef
	} from '#lib/stores/selection.js';
	import {
		fetchDatasetsForFeatures,
		fetchAllDatasets,
		fetchDatasetDetail,
		fetchDatasetCategories,
		fetchFeatureIds,
		type DatasetSummary,
		type DatasetDetail,
		type DatasetCategory,
		type DatasetFilter
	} from '#lib/api.js';
	import { type FilterSelection } from '#lib/stores/cart.js';
	import { customBoundary } from '#lib/stores/customBoundary.js';
	import { bbox as turfBbox } from '@turf/bbox';
	import { ChevronRight, TriangleAlert } from '@lucide/svelte';
	import DatasetMetadata from '#lib/components/datasets/DatasetMetadata.svelte';
	import DatasetSelector from '#lib/components/datasets/DatasetSelector.svelte';
	import RasterOptions from '#lib/components/datasets/RasterOptions.svelte';
	import FilterAndAggOptions from '#lib/components/datasets/FilterAndAggOptions.svelte';
	import OutcomeSelector from '#lib/components/datasets/OutcomeSelector.svelte';
	import MoreOptionsHint from '#lib/components/datasets/MoreOptionsHint.svelte';
	import DatasetActions from '#lib/components/datasets/DatasetActions.svelte';
	import RequestPanel from '#lib/components/layout/RequestPanel.svelte';
	import RecipeNotice from '#lib/components/layout/RecipeNotice.svelte';
	import { rememberCoverage } from '#lib/stores/coverageCounts.js';
	import OutputSummary from '#lib/components/datasets/OutputSummary.svelte';
	import VersionCards from '#lib/components/datasets/VersionCards.svelte';
	import { columnsByDataset, cleanVersionName, invalidVersionNames, narrowedFilters, uniqueVersionName } from '#lib/utils/outputColumns.js';
	import { Button } from '#lib/components/ui/button/index.js';

	$effect(() => {
		currentStep.set('search');
	});

	let isCustomMode = $derived($customBoundary.saved && $customBoundary.active);

	// The selection comes from the store, which survives a refresh in the
	// tab's saved state (stores/tabState.ts); with none, back to the map.
	$effect(() => {
		if (!isCustomMode && !$selection) goto('/');
	});

	// The selected boundary sets, named as in the selection legend, for the
	// dataset list's coverage chips
	let boundarySets = $derived.by(() => {
		const sel = $selection;
		if (!sel || isCustomMode) return [];
		const fcs = sel.mode === 'single' ? [sel.fc] : sel.fcs;
		return fcs.map((fc) => ({ id: fc.id, title: fc.title ?? fc.short_name ?? fc.name }));
	});

	// Resolved feature IDs from the store (set by map page before navigation)
	let resolvedIds = $derived($selection?.resolvedFeatureIds ?? []);

	// If the user arrived directly (e.g. browser back/forward) without resolved IDs,
	// re-resolve from the FC IDs so the page still works.
	$effect(() => {
		if (!$selection || resolvedIds.length > 0) return;
		const fcIds = $selectionFcIds;
		if (!fcIds.length) return;
		fetchFeatureIds(fcIds)
			.then((ids) => selection.setResolvedFeatureIds(ids))
			.catch(console.error);
	});

	// Bbox of the user's uploaded boundary for out-of-range flagging
	let userBbox = $derived.by((): [number, number, number, number] | null => {
		if (!isCustomMode || !$customBoundary.finalFeatures) return null;
		try { return turfBbox($customBoundary.finalFeatures) as [number, number, number, number]; }
		catch { return null; }
	});

	function bboxesIntersect(
		a: [number, number, number, number],
		b: [number, number, number, number]
	): boolean {
		return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1];
	}

	let outOfRangeNames = $derived.by((): Set<string> => {
		if (!userBbox) return new Set();
		return new Set(
			datasets
				.filter((d) => d.bbox !== null && !bboxesIntersect(userBbox!, d.bbox!))
				.map((d) => d.name)
		);
	});

	// Data loading state
	let datasets = $state<DatasetSummary[]>([]);
	let categories = $state<DatasetCategory[]>([]);
	let loadError = $state<string | null>(null);

	// Currently selected dataset (summary from the list)
	let selectedDatasetSummary = $state<DatasetSummary | null>(null);
	// Full detail for the selected dataset
	let selectedDatasetDetail = $state<DatasetDetail | null>(null);
	let detailLoading = $state(false);
	// The options pane, which scrolls; MoreOptionsHint watches it
	let optionsPane = $state<HTMLElement | undefined>();
	// Custom filters shown, by dataset, once toggled (GEO-164); until then,
	// shown only when the selection already narrows a filter.
	let filtersOpen = $state<Record<string, boolean>>({});
	// Metadata panels stay as the user left them while switching datasets.
	let metadataCiteOpen = $state(false);
	let metadataMoreOpen = $state(false);

	// Raster options state
	let rasterOptions = $state<{ extractTypes: string[]; resources: string[] }>({
		extractTypes: [],
		resources: []
	});

	// Filter-and-agg state
	let filterSelections = $state<Record<string, FilterSelection>>({});
	let selectedOutcome = $state<string>('');

	function buildFilterKwargs(
		selections: Record<string, FilterSelection>,
		filters: Record<string, DatasetFilter> | null,
		outcome: string
	): Record<string, unknown> {
		const kwargs: Record<string, unknown> = {};
		if (outcome) kwargs.outcome = outcome;
		for (const [key, sel] of Object.entries(selections)) {
			const aggregate = filters?.[key]?.aggregate ?? true;
			kwargs[key] = { ...sel, aggregate };
		}
		return kwargs;
	}

	function initFilterSelections(filters: Record<string, DatasetFilter>): Record<string, FilterSelection> {
		const s: Record<string, FilterSelection> = {};
		for (const [key, f] of Object.entries(filters)) {
			if (f.type === 'range') {
				s[key] = { type: 'range', start: f.min, end: f.max };
			} else {
				s[key] = { type: 'categorical', selected: [...f.categories] };
			}
		}
		return s;
	}

	// A new feature selection (GEO-153): nothing chosen in what's required (the
	// measure, and values for any fields it splits by), and no filter narrowing
	// the records. Like a raster, so opening one doesn't add it. The measure
	// isn't preselected even when there's only one: choosing it is what adds a
	// dataset with nothing to split by.
	function newSelections(detail: DatasetDetail): Record<string, FilterSelection> {
		const s = initFilterSelections(detail.filters!);
		for (const [key, f] of Object.entries(detail.filters ?? {})) {
			if (f.aggregate === false && f.type === 'categorical') s[key] = { type: 'categorical', selected: [] };
		}
		return s;
	}
	function newOutcome(_detail: DatasetDetail): string {
		return '';
	}

	/** Some split value chosen, from a selection's kwargs: worth a mark in the list while incomplete */
	const kwargsStarted = (kwargs: Record<string, unknown> | undefined) =>
		Object.values(kwargs ?? {}).some(
			(v) => !!v && typeof v === 'object' && (v as { aggregate?: boolean }).aggregate === false && ((v as { selected?: unknown[] }).selected?.length ?? 0) > 0
		);

	function isFeature(detail: DatasetDetail | null): boolean {
		return detail?.processing_class === 'filter_and_agg' && !!detail.filters;
	}

	const kwargsKey = (kwargs: Record<string, unknown> | null | undefined) => JSON.stringify(kwargs ?? null);

	// How options are saved (GEO-104, GEO-153): as they change, for both kinds.
	// - Rasters: one cart entry per dataset, replaced on every change, once
	//   there's a measure (and a period, when it has them); incomplete choices
	//   wait in datasetChoices.
	// - Feature datasets: any number of selections, each its own cart entry.
	//   The one being edited is kept in datasetChoices, and in the cart (as
	//   editingKey) whenever it's complete. "New selection" starts another.
	// datasetChoices is a store, so all of this survives leaving the page.

	/** A raster dataset's cart entry (rasters have at most one). */
	function rasterCartItem(name: string): CartItem | undefined {
		return $cart.find((i) => i.datasetName === name && i.kwargs == null);
	}

	function buildRasterItem(detail: DatasetDetail, options: { extractTypes: string[]; resources: string[] }): CartItem {
		return {
			// Keep a name the user gave it on the Review page.
			customName: rasterCartItem(detail.name)?.customName ?? detail.title ?? detail.name,
			datasetName: detail.name,
			datasetTitle: detail.title ?? detail.name,
			datasetType: detail.type,
			processingClass: detail.processing_class,
			extractTypes: [...options.extractTypes],
			resources: [...options.resources],
			resourceLabels: options.resources.map((name) => {
				const res = detail.resources.find((r) => r.name === name);
				return res?.label ?? res?.temporal ?? name;
			})
		};
	}

	// Feature datasets: the kwargs the open dataset's filters produce, and
	// whether the cart already holds exactly those.
	const currentKwargs = $derived(
		selectedDatasetDetail && isFeature(selectedDatasetDetail)
			? buildFilterKwargs(filterSelections, selectedDatasetDetail.filters, selectedOutcome)
			: null
	);
	// The cart entry the options shown are (the selection being edited), while
	// it's in the cart; null while the selection is incomplete.
	const editingKey = $derived.by(() => {
		const detail = selectedDatasetDetail;
		if (!detail) return null;
		const key = $datasetChoices[detail.name]?.editingKey;
		return key && $cart.some((i) => i.datasetName === detail.name && kwargsKey(i.kwargs) === key) ? key : null;
	});

	// Another selection of this dataset with exactly the options shown: these
	// aren't saved over it, or as a second copy of it.
	const duplicateOf = $derived.by(() => {
		const detail = selectedDatasetDetail;
		if (!detail || !currentKwargs) return null;
		const key = kwargsKey(currentKwargs);
		if (key === editingKey) return null;
		const hit = $cart.find((i) => i.datasetName === detail.name && kwargsKey(i.kwargs) === key);
		return hit ? hit.customName || detail.title || detail.name : null;
	});

	/**
	 * Whether a raster's options make a complete request entry: at least one
	 * extract option, and at least one time period when the dataset has them
	 * (the same rule RasterOptions uses to show the Time Periods card).
	 */
	function rasterComplete(detail: DatasetDetail, options: { extractTypes: string[]; resources: string[] }): boolean {
		const hasPeriods = detail.temporal_name !== 'Temporally Invariant' && detail.resources.length > 0;
		return options.extractTypes.length > 0 && (!hasPeriods || options.resources.length > 0);
	}

	// Whether the open dataset's options differ from where it starts, so Reset
	// has something to do (GEO-162): any raster option chosen, or feature
	// options changed from their defaults.
	const canReset = $derived.by(() => {
		const detail = selectedDatasetDetail;
		if (!detail) return false;
		if (!isFeature(detail)) return rasterOptions.extractTypes.length > 0 || rasterOptions.resources.length > 0;
		const defaults = buildFilterKwargs(newSelections(detail), detail.filters, newOutcome(detail));
		return kwargsKey(currentKwargs) !== kwargsKey(defaults);
	});

	/**
	 * A feature dataset's required options that aren't chosen (GEO-163): a
	 * measure, and at least one value in each field the results are split by,
	 * when it has any. Many feature datasets split by nothing.
	 */
	function featureMissing(
		detail: DatasetDetail,
		outcome: string,
		selections: Record<string, FilterSelection>
	): { measure: boolean; splits: Set<string> } {
		const splits = new Set<string>();
		for (const [key, f] of Object.entries(detail.filters ?? {})) {
			const sel = selections[key];
			if (f.aggregate === false && f.type === 'categorical' && sel?.type === 'categorical' && sel.selected.length === 0) {
				splits.add(key);
			}
		}
		return { measure: Object.keys(detail.outcomes ?? {}).length > 0 && !outcome, splits };
	}

	// What's missing from the open dataset, and whether to mark it: only once
	// something has been chosen, so a dataset just opened isn't all red.
	const missing = $derived.by(() => {
		const detail = selectedDatasetDetail;
		const none = { measure: false, periods: false, splits: new Set<string>(), any: false, show: false };
		if (!detail) return none;
		if (isFeature(detail)) {
			const m = featureMissing(detail, selectedOutcome, filterSelections);
			const chosen =
				!!selectedOutcome ||
				Object.entries(detail.filters ?? {}).some(
					([key, f]) => f.aggregate === false && (filterSelections[key] as { selected?: unknown[] })?.selected?.length
				);
			const any = m.measure || m.splits.size > 0;
			return { ...none, measure: m.measure, splits: m.splits, any, show: any && chosen };
		}
		const hasPeriods = detail.temporal_name !== 'Temporally Invariant' && detail.resources.length > 0;
		const measure = rasterOptions.extractTypes.length === 0;
		const periods = hasPeriods && rasterOptions.resources.length === 0;
		const chosen = rasterOptions.extractTypes.length > 0 || rasterOptions.resources.length > 0;
		return { ...none, measure, periods, any: measure || periods, show: (measure || periods) && chosen };
	});

	// "a measure and a value for Year", for the status line
	const featureMissingText = $derived.by(() => {
		const detail = selectedDatasetDetail;
		if (!detail || !isFeature(detail) || !missing.any) return null;
		const parts = [
			missing.measure ? 'a measure' : null,
			...[...missing.splits].map((key) => `a ${detail.filters?.[key]?.display ?? key} value`)
		].filter(Boolean) as string[];
		return parts.length <= 2 ? parts.join(' and ') : `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}`;
	});

	/** What the summary panel shows about the open dataset. */
	const saveState = $derived.by((): 'saved' | 'incomplete' | 'duplicate' | null => {
		const detail = selectedDatasetDetail;
		if (!detail) return null;
		if (isFeature(detail)) {
			if (missing.any) return 'incomplete';
			return duplicateOf ? 'duplicate' : 'saved';
		}
		return rasterComplete(detail, rasterOptions) ? 'saved' : 'incomplete';
	});

	// Marks in the dataset list: in the request (check), or feature choices
	// that differ from everything in the request (exclamation).
	const inRequestNames = $derived(new Set($cart.map((i) => i.datasetName)));
	const unsavedNames = $derived.by(() => {
		// A feature selection started but not complete (not in the request)
		const names = new Set<string>();
		for (const [name, choices] of Object.entries($datasetChoices)) {
			const inCart = !!choices.editingKey && $cart.some((i) => i.datasetName === name && kwargsKey(i.kwargs) === choices.editingKey);
			if (choices.kwargs && !inCart && kwargsStarted(choices.kwargs)) names.add(name);
		}
		return names;
	});

	// Opening a feature dataset: the selection being edited (from Review's
	// "Edit options", or before leaving the page), else its first selection in
	// the request, else a new one (GEO-153).
	$effect(() => {
		const detail = selectedDatasetDetail;
		if (!detail || !isFeature(detail)) return;
		untrack(() => {
			const saved = datasetChoices.get(detail.name);
			if (saved?.filterSelections) {
				filterSelections = structuredClone(saved.filterSelections);
				selectedOutcome = saved.selectedOutcome ?? '';
				return;
			}
			const first = $cart.find((i) => i.datasetName === detail.name && i.kwargs != null);
			if (first) editVersion(first);
			else {
				filterSelections = newSelections(detail);
				selectedOutcome = newOutcome(detail);
			}
		});
	});

	// Fetch datasets when resolved feature IDs become available (standard) or in custom mode
	$effect(() => {
		const ids = resolvedIds;
		const custom = isCustomMode;
		if (!ids.length && !custom) return;

		loadError = null;

		// With the boundary sets, each dataset also says which of them it covers (GEO-127)
		const fcIds = untrack(() => $selectionFcIds);
		const datasetPromise = custom ? fetchAllDatasets() : fetchDatasetsForFeatures(ids, fcIds);

		Promise.all([datasetPromise, fetchDatasetCategories()])
			.then(([ds, cats]) => {
				datasets = ds;
				categories = cats;
				if (!custom) {
					// Kept for the panel's Customize Datasets summary on Review
					rememberCoverage(ids, ds.length);
					const covered = new Set(ds.map((d) => d.name));
					const current = get(cart);
					if (current.length > 0) {
						cart.setItems(current.filter((item) => covered.has(item.datasetName)));
					}
				}
			})
			.catch((err) => {
				loadError = err.message;
				console.error('Failed to load datasets:', err);
			});
	});

	// Opened from the Review page's "Edit options" link (?dataset=name):
	// open that dataset once the list has loaded.
	let openedFromLink = false;
	$effect(() => {
		const wanted = page.url.searchParams.get('dataset');
		if (!wanted || openedFromLink || datasets.length === 0) return;
		const dataset = datasets.find((d) => d.name === wanted);
		if (dataset) {
			openedFromLink = true;
			untrack(() => handleDatasetSelect(dataset));
		}
	});

	// Fetch full detail when a dataset is selected
	$effect(() => {
		if (!selectedDatasetSummary) {
			selectedDatasetDetail = null;
			return;
		}

		detailLoading = true;
		fetchDatasetDetail(selectedDatasetSummary.name)
			.then((detail) => {
				selectedDatasetDetail = detail;
			})
			.catch((err) => {
				console.error('Failed to load dataset detail:', err);
				selectedDatasetDetail = null;
			})
			.finally(() => {
				detailLoading = false;
			});
	});

	function handleDatasetSelect(dataset: DatasetSummary) {
		// On a narrow screen the dataset takes over the screen (lib/stepDetail.ts),
		// even the one already open
		openDetail();
		if (dataset.name === selectedDatasetSummary?.name) return;
		// Drop the old detail now, so nothing can save the next dataset's
		// choices under the previous name while its detail loads.
		selectedDatasetDetail = null;
		selectedDatasetSummary = dataset;
		const inCart = rasterCartItem(dataset.name);
		const waiting = datasetChoices.get(dataset.name)?.rasterOptions;
		rasterOptions = inCart
			? { extractTypes: [...(inCart.extractTypes ?? [])], resources: [...(inCart.resources ?? [])] }
			: waiting
				? { extractTypes: [...waiting.extractTypes], resources: [...waiting.resources] }
				: { extractTypes: [], resources: [] };
	}

	function handleRasterChange(options: { extractTypes: string[]; resources: string[] }) {
		rasterOptions = options;
		const detail = selectedDatasetDetail;
		if (!detail) return;
		if (rasterComplete(detail, options)) {
			cart.setRasterItem(buildRasterItem(detail, options));
			datasetChoices.clear(detail.name);
		} else {
			// Not complete yet: out of the request, but keep what's been chosen.
			cart.removeRasterItem(detail.name);
			if (options.extractTypes.length > 0 || options.resources.length > 0) {
				datasetChoices.save(detail.name, { rasterOptions: $state.snapshot(options) });
			} else {
				datasetChoices.clear(detail.name);
			}
		}
	}

	/**
	 * Save the feature selection being edited, as it changes (GEO-153).
	 * Complete, it's in the cart: replacing its entry in place, or added as a
	 * new one. Incomplete, or the same as another selection, it's out of the
	 * cart (keeping its name for when it's back), and its card says why.
	 */
	function saveFeatureChoices() {
		const detail = selectedDatasetDetail;
		if (!detail || !isFeature(detail)) return;
		// Plain copies: the store clones what it's given, and reactive proxies
		// can't be cloned.
		const selections = $state.snapshot(filterSelections);
		const kwargs = buildFilterKwargs(selections, detail.filters, selectedOutcome);
		const key = kwargsKey(kwargs);
		const prev = datasetChoices.get(detail.name);
		const items = get(cart);
		const editIdx = prev?.editingKey
			? items.findIndex((i) => i.datasetName === detail.name && kwargsKey(i.kwargs) === prev.editingKey)
			: -1;
		const m = featureMissing(detail, selectedOutcome, selections);
		const complete = !m.measure && m.splits.size === 0;
		const duplicate = items.some((i, idx) => idx !== editIdx && i.datasetName === detail.name && kwargsKey(i.kwargs) === key);

		let editingKey = editIdx >= 0 ? prev!.editingKey : undefined;
		let customName = prev?.customName;
		if (complete && !duplicate) {
			const item = buildFeatureItem(detail, selections, customName);
			if (editIdx >= 0) cart.replaceAt(editIdx, item);
			else cart.addItem(item);
			editingKey = key;
			customName = undefined;
		} else if (editIdx >= 0) {
			// Incomplete, or now the same as another selection: out of the request
			customName = items[editIdx].customName;
			cart.removeItem(editIdx);
			editingKey = undefined;
		}
		datasetChoices.save(detail.name, { filterSelections: selections, selectedOutcome, kwargs, editingKey, customName });
	}

	function buildFeatureItem(detail: DatasetDetail, selections: Record<string, FilterSelection>, name?: string): CartItem {
		const items = get(cart);
		return {
			// Unique per selection: it prefixes this selection's output columns
			customName:
				name && !items.some((i) => i.customName === name) ? name : uniqueVersionName(cleanVersionName(detail.name), items),
			datasetName: detail.name,
			datasetTitle: detail.title ?? detail.name,
			datasetType: detail.type,
			processingClass: detail.processing_class,
			filterSelections: selections,
			kwargs: buildFilterKwargs(selections, detail.filters, selectedOutcome)
		};
	}

	// The open feature dataset's versions in the request, shown as cards
	const featureEntries = $derived(
		selectedDatasetDetail && isFeature(selectedDatasetDetail)
			? $cart
					.map((item, index) => ({ item, index }))
					.filter(({ item }) => item.datasetName === selectedDatasetDetail!.name)
			: []
	);
	const invalidNames = $derived(invalidVersionNames($cart));

	/** Load a selection from the request into the options, to edit it. */
	function editVersion(item: CartItem) {
		const detail = selectedDatasetDetail;
		if (!detail || !item.kwargs) return;
		filterSelections = structuredClone(item.filterSelections ?? initFilterSelections(detail.filters!));
		const outcome = item.kwargs.outcome;
		selectedOutcome = typeof outcome === 'string' ? outcome : newOutcome(detail);
		datasetChoices.save(detail.name, {
			filterSelections: $state.snapshot(filterSelections),
			selectedOutcome,
			kwargs: item.kwargs,
			editingKey: kwargsKey(item.kwargs)
		});
	}

	/** "New selection": the one being edited stays in the request; start another. */
	function newSelection() {
		const detail = selectedDatasetDetail;
		if (!detail || !isFeature(detail)) return;
		filterSelections = newSelections(detail);
		selectedOutcome = newOutcome(detail);
		datasetChoices.save(detail.name, {
			filterSelections: $state.snapshot(filterSelections),
			selectedOutcome,
			kwargs: buildFilterKwargs($state.snapshot(filterSelections), detail.filters, selectedOutcome)
		});
	}

	/** Remove a selection; removing the one being edited moves to another, or a new one. */
	function removeVersion(index: number) {
		const detail = selectedDatasetDetail;
		const removedKey = kwargsKey($cart[index]?.kwargs);
		cart.removeItem(index);
		if (!detail || removedKey !== editingKey) return;
		datasetChoices.clear(detail.name);
		const next = get(cart).find((i) => i.datasetName === detail.name && i.kwargs != null);
		if (next) editVersion(next);
		else newSelection();
	}

	function handleReset() {
		const detail = selectedDatasetDetail;
		if (!detail) return;
		if (isFeature(detail)) {
			// Only the selection being edited: back to a new selection's options,
			// which takes it out of the request. Other selections stay.
			filterSelections = newSelections(detail);
			selectedOutcome = newOutcome(detail);
			saveFeatureChoices();
		} else {
			datasetChoices.clear(detail.name);
			rasterOptions = { extractTypes: [], resources: [] };
			cart.removeRasterItem(detail.name);
		}
	}

	// Clear All (GEO-152), as on the boundary step: takes every dataset out of
	// the request, drops the choices waiting on incomplete ones, and resets the
	// open dataset's form. The boundaries stay.
	function clearAllDatasets() {
		cart.clear();
		datasetChoices.clearAll();
		const detail = selectedDatasetDetail;
		rasterOptions = { extractTypes: [], resources: [] };
		if (detail && isFeature(detail)) {
			filterSelections = newSelections(detail);
			selectedOutcome = newOutcome(detail);
		}
	}
</script>

<Seo title="Customize Datasets" description="Browse GeoQuery's datasets, including population, nighttime lights, climate, land cover, conflict and health, and choose the years and statistics to extract for your boundaries." />

<div class="flex h-[calc(100dvh-var(--header-height,8rem))]">
	<RequestPanel active="search" bare>
		<RecipeNotice />
		{#if !resolvedIds.length && !isCustomMode}
			<p class="px-4 py-6 text-sm text-muted-foreground">Loading available datasets…</p>
		{:else if loadError}
			<div class="px-4 py-6">
				<p class="font-bold text-destructive">Failed to load datasets</p>
				<p class="mt-2 text-sm text-muted-foreground">{loadError}</p>
			</div>
		{:else}
			<div class="min-h-0 flex-1">
				<DatasetSelector
					{datasets}
					{categories}
					selectedDataset={selectedDatasetSummary}
					onSelect={handleDatasetSelect}
					{outOfRangeNames}
					{unsavedNames}
					columnCounts={columnsByDataset($cart)}
					{boundarySets}
				/>
			</div>
		{/if}
		<!-- Laid out as the boundary step's: Clear All at the left once there's
		     something to clear, and on to the next step at the right, always
		     here but disabled until the request has a dataset in it. (Submit
		     Request on Review stays full width, as the last step.) -->
		<div class="flex items-center justify-between gap-2 border-t px-4 py-2.5">
			{#if $cartCount > 0 || Object.keys($datasetChoices).length > 0}
				<Button size="sm" variant="outline" onclick={clearAllDatasets} class="text-muted-foreground hover:text-destructive">
					Clear All
				</Button>
			{:else}
				<span></span>
			{/if}
			<Button size="sm" disabled={$cartCount === 0} onclick={() => goto('/review')}>
				Continue to Review
				<ChevronRight />
			</Button>
		</div>
	</RequestPanel>

	<!-- The open dataset, beside the panel -->
	<div class="step-main flex min-w-0 flex-1 flex-col">
		<!-- Narrow screens: back to the list, "Done" once this dataset is in the request -->
		<div class="border-b bg-card px-4 py-2 md:hidden">
			{#if selectedDatasetSummary && inRequestNames.has(selectedDatasetSummary.name)}
				<DetailBack label="Done" done />
			{:else}
				<DetailBack label="Datasets" />
			{/if}
		</div>
		{#if isCustomMode}
			<div class="flex items-center gap-2 bg-warning-bg px-4 py-2 text-sm text-foreground" role="note">
				<TriangleAlert class="size-4 shrink-0 text-warning-text" aria-hidden="true" />
				<span>
					<strong>Custom boundary:</strong> Precise coverage cannot be verified. All datasets are shown.
					Datasets flagged <span class="font-bold">out of range</span> likely have no data for your area.
				</span>
			</div>
		{/if}

		<!-- Center Panel: Dataset Configuration. Scrolls vertically only. -->
		<div bind:this={optionsPane} class="min-w-0 flex-1 overflow-y-auto overflow-x-hidden bg-background">
			{#if !selectedDatasetDetail && !detailLoading}
				<div class="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
					<p class="text-muted-foreground">
						{selectedDatasetSummary
							? 'Loading dataset configuration...'
							: 'Select a dataset from the list to configure it.'}
					</p>
					{#if !selectedDatasetSummary}
						<p class="max-w-md text-xs text-muted-foreground">
							A dataset joins your request as soon as its options are complete. Datasets of events
							or locations, such as conflict events, can be added more than once, each selection
							with its own options.
						</p>
					{/if}
				</div>
			{:else if detailLoading}
				<div class="flex h-full items-center justify-center">
					<p class="text-muted-foreground">Loading dataset details...</p>
				</div>
			{:else if selectedDatasetDetail}
				<!-- Dataset title bar -->
				<div class="border-b bg-muted/30 px-4 py-3">
					<h2 class="">
						{selectedDatasetDetail.title ?? selectedDatasetDetail.name}
					</h2>
					{#if selectedDatasetDetail.description}
						<p class="mt-1 text-sm text-muted-foreground">
							{selectedDatasetDetail.description}
						</p>
					{/if}
					<DatasetMetadata
						dataset={selectedDatasetDetail}
						bbox={selectedDatasetSummary?.bbox}
						bind:citeOpen={metadataCiteOpen}
						bind:moreOpen={metadataMoreOpen}
					/>
				</div>

				{#if isFeature(selectedDatasetDetail)}
					<!-- The dataset's selections, one card each: the one being edited
					     (incomplete ones only exist here), and New selection -->
					<VersionCards
						dataset={selectedDatasetDetail}
						entries={featureEntries}
						invalid={invalidNames}
						onRename={(index, name) => cart.updateItemName(index, name)}
						onRemove={removeVersion}
						{editingKey}
						onEdit={editVersion}
						draft={editingKey
							? null
							: {
									name: $datasetChoices[selectedDatasetDetail.name]?.customName ?? 'New selection',
									problem: duplicateOf
										? `Same options as “${duplicateOf}”, which is already in your request.`
										: 'Not in your request until its options are complete.'
								}}
						onNew={newSelection}
						canNew={saveState === 'saved'}
					/>
				{/if}

				<h3 class="px-4 pt-4 text-base font-semibold">Select Dataset Options</h3>
				<!-- Where the options stand, in one line, with Reset at its end (GEO-164) -->
				<OutputSummary
					dataset={selectedDatasetDetail}
					isFeature={isFeature(selectedDatasetDetail)}
					extractTypes={rasterOptions.extractTypes}
					resources={rasterOptions.resources}
					{filterSelections}
					outcome={selectedOutcome}
					{saveState}
					{featureMissingText}
					{duplicateOf}
				>
					{#snippet actions()}
						<DatasetActions isFeature={isFeature(selectedDatasetDetail)} onReset={handleReset} {canReset} />
					{/snippet}
				</OutputSummary>
				{#if selectedDatasetDetail.processing_class === 'filter_and_agg' && selectedDatasetDetail.filters}
					{@const detail = selectedDatasetDetail}
					{@const filterCount = Object.values(detail.filters!).filter((f) => f.aggregate !== false).length}
					{@const narrowed = narrowedFilters(detail.filters, filterSelections).length}
					{@const showFilters = filtersOpen[detail.name] ?? narrowed > 0}
					{@const onSelectionsChange = (s: Record<string, FilterSelection>) => {
						filterSelections = s;
						saveFeatureChoices();
					}}
					<!-- Custom filters (hidden until asked for, or already narrowing this
					     selection), then Measure and Split results by -->
					<div class="mt-4 space-y-4 pb-4">
					{#if filterCount > 0}
						<div class="px-4">
							<Button
								variant="outline"
								size="sm"
								aria-expanded={showFilters}
								aria-controls="custom-filters"
								onclick={() => (filtersOpen = { ...filtersOpen, [detail.name]: !showFilters })}
							>
								<ChevronRight class="transition-transform {showFilters ? 'rotate-90' : ''}" />
								Custom filters
								{#if narrowed > 0}<span class="font-normal text-muted-foreground">({narrowed} applied)</span>{/if}
							</Button>
						</div>
						{#if showFilters}
							<div id="custom-filters">
								<FilterAndAggOptions part="filter" filters={detail.filters!} selections={filterSelections} {onSelectionsChange} />
							</div>
						{/if}
					{/if}
					{#if detail.outcomes}
						<OutcomeSelector
							outcomes={detail.outcomes}
							selected={selectedOutcome}
							missing={missing.show && missing.measure}
							onSelect={(key) => {
								selectedOutcome = key;
								saveFeatureChoices();
							}}
						/>
					{/if}
					<FilterAndAggOptions
						part="split"
						filters={detail.filters!}
						selections={filterSelections}
						missingSplits={missing.show ? missing.splits : undefined}
						{onSelectionsChange}
					/>
					</div>
				{:else}
					<RasterOptions
						dataset={selectedDatasetDetail}
						options={rasterOptions}
						onOptionsChange={handleRasterChange}
						missing={{ measure: missing.show && missing.measure, periods: missing.show && missing.periods }}
					/>
				{/if}
				<MoreOptionsHint scroller={optionsPane} />
			{/if}
		</div>
	</div>
</div>
