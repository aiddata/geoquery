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
	import { columnsByDataset, cleanVersionName, invalidVersionNames, uniqueVersionName } from '#lib/utils/outputColumns.js';
	import { mergeFeatureVersions, versionCovers } from '#lib/utils/featureMerge.js';
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

	function defaultOutcome(detail: DatasetDetail): string {
		return detail.outcomes ? (Object.keys(detail.outcomes)[0] ?? '') : '';
	}

	function isFeature(detail: DatasetDetail | null): boolean {
		return detail?.processing_class === 'filter_and_agg' && !!detail.filters;
	}

	const kwargsKey = (kwargs: Record<string, unknown> | null | undefined) => JSON.stringify(kwargs ?? null);

	// How options are saved (GEO-104):
	// - Rasters go straight into the cart as they change: one entry per
	//   dataset, replaced on every change. At least one extract option makes a
	//   valid entry; none (or Reset) removes it. Choices that aren't valid yet
	//   wait in datasetChoices.
	// - Feature datasets keep their current filters in datasetChoices, and
	//   still need Add to Request. Each distinct set of filters is its own
	//   cart entry, so a dataset can be added more than once.
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
	// In the request already: an identical version, or one that covers these
	// options (adding them would merge in nothing). The version being edited
	// counts only when identical, so narrowing it can still be saved.
	const featureSaved = $derived(
		!!currentKwargs &&
			$cart.some(
				(i) =>
					i.datasetName === selectedDatasetDetail?.name &&
					(kwargsKey(i.kwargs) === kwargsKey(currentKwargs) ||
						(kwargsKey(i.kwargs) !== editingKey && versionCovers(i, currentKwargs!)))
			)
	);

	// The version Add would merge these options into (same filters and measure,
	// other years), so the button can say so.
	const mergeTarget = $derived.by(() => {
		const detail = selectedDatasetDetail;
		if (!detail || !currentKwargs || featureSaved) return null;
		const hit = $cart.find(
			(i) =>
				i.datasetName === detail.name &&
				kwargsKey(i.kwargs) !== editingKey &&
				mergeFeatureVersions(i, { ...i, kwargs: currentKwargs! })
		);
		return hit ? hit.customName || detail.title || detail.name : null;
	});

	// Opened from the Review page's "Edit options": the cart entry being
	// edited, while it's still in the cart. Update Request replaces it.
	const editingKey = $derived.by(() => {
		const detail = selectedDatasetDetail;
		if (!detail) return null;
		const key = $datasetChoices[detail.name]?.editingKey;
		return key && $cart.some((i) => i.datasetName === detail.name && kwargsKey(i.kwargs) === key) ? key : null;
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

	/** What the summary panel shows about the open dataset. */
	const saveState = $derived.by((): 'saved' | 'unsaved' | 'editing' | 'incomplete' | null => {
		const detail = selectedDatasetDetail;
		if (!detail) return null;
		if (isFeature(detail)) return featureSaved ? 'saved' : editingKey ? 'editing' : 'unsaved';
		return rasterComplete(detail, rasterOptions) ? 'saved' : 'incomplete';
	});

	// Marks in the dataset list: in the request (check), or feature choices
	// that differ from everything in the request (exclamation).
	const inRequestNames = $derived(new Set($cart.map((i) => i.datasetName)));
	const unsavedNames = $derived.by(() => {
		const names = new Set<string>();
		for (const [name, choices] of Object.entries($datasetChoices)) {
			if (!choices.kwargs) continue;
			const key = kwargsKey(choices.kwargs);
			const covered = $cart.some(
				(i) =>
					i.datasetName === name &&
					(kwargsKey(i.kwargs) === key ||
						(kwargsKey(i.kwargs) !== choices.editingKey && versionCovers(i, choices.kwargs!)))
			);
			if (!covered) names.add(name);
		}
		return names;
	});

	// Load a feature dataset's saved filters (or its defaults) when it opens.
	$effect(() => {
		const detail = selectedDatasetDetail;
		const saved = detail ? untrack(() => datasetChoices.get(detail.name)) : undefined;
		if (detail && isFeature(detail)) {
			filterSelections = saved?.filterSelections
				? structuredClone(saved.filterSelections)
				: initFilterSelections(detail.filters!);
		}
		selectedOutcome = detail ? (saved?.selectedOutcome ?? defaultOutcome(detail)) : '';
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

	function saveFeatureChoices() {
		const detail = selectedDatasetDetail;
		if (!detail || !isFeature(detail)) return;
		// Plain copies: the store clones what it's given, and reactive proxies
		// can't be cloned.
		const selections = $state.snapshot(filterSelections);
		datasetChoices.save(detail.name, {
			filterSelections: selections,
			selectedOutcome,
			kwargs: buildFilterKwargs(selections, detail.filters, selectedOutcome),
			editingKey: datasetChoices.get(detail.name)?.editingKey
		});
	}

	function buildFeatureItem(detail: DatasetDetail): CartItem {
		const selections = $state.snapshot(filterSelections);
		return {
			// Unique per version: it prefixes this version's output columns
			customName: uniqueVersionName(cleanVersionName(detail.name), $cart),
			datasetName: detail.name,
			datasetTitle: detail.title ?? detail.name,
			datasetType: detail.type,
			processingClass: detail.processing_class,
			filterSelections: selections,
			kwargs: buildFilterKwargs(selections, detail.filters, selectedOutcome)
		};
	}

	/** Leave edit mode: the filters stay, but no longer replace an entry. */
	// The open feature dataset's versions in the request, shown as cards
	const featureEntries = $derived(
		selectedDatasetDetail && isFeature(selectedDatasetDetail)
			? $cart
					.map((item, index) => ({ item, index }))
					.filter(({ item }) => item.datasetName === selectedDatasetDetail!.name)
			: []
	);
	const invalidNames = $derived(invalidVersionNames($cart));

	/** Load a version from the request into the options, to edit and replace it. */
	function editVersion(item: CartItem) {
		const detail = selectedDatasetDetail;
		if (!detail || !item.kwargs) return;
		filterSelections = structuredClone(item.filterSelections ?? initFilterSelections(detail.filters!));
		const outcome = item.kwargs.outcome;
		selectedOutcome = typeof outcome === 'string' ? outcome : defaultOutcome(detail);
		datasetChoices.save(detail.name, {
			filterSelections: $state.snapshot(filterSelections),
			selectedOutcome,
			kwargs: item.kwargs,
			editingKey: kwargsKey(item.kwargs)
		});
	}

	function stopEditing(name: string) {
		const choices = datasetChoices.get(name);
		if (choices?.editingKey) datasetChoices.save(name, { ...choices, editingKey: undefined });
	}

	/** Replace the entry opened with "Edit options" with the current filters. */
	function handleUpdateRequest() {
		const detail = selectedDatasetDetail;
		if (!detail || !isFeature(detail) || !editingKey) return;
		cart.replaceFeatureItem(detail.name, editingKey, buildFeatureItem(detail));
		stopEditing(detail.name);
	}

	/** Feature datasets only: rasters are already in the cart. Adds a new version. */
	function handleAddToRequest() {
		const detail = selectedDatasetDetail;
		if (!detail || !isFeature(detail)) return;
		cart.upsertItem(buildFeatureItem(detail));
		stopEditing(detail.name);
	}

	function handleReset() {
		const detail = selectedDatasetDetail;
		if (!detail) return;
		datasetChoices.clear(detail.name);
		if (isFeature(detail)) {
			// Entries already added stay in the request; Reset only clears the form.
			filterSelections = initFilterSelections(detail.filters!);
			selectedOutcome = defaultOutcome(detail);
		} else {
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
			filterSelections = initFilterSelections(detail.filters!);
			selectedOutcome = defaultOutcome(detail);
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
							Raster datasets join your request as soon as you choose their options. Feature
							datasets need <strong>Add to Request</strong>, and can be added more than once with
							different filters.
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

				{#if featureEntries.length > 0}
					<VersionCards
						dataset={selectedDatasetDetail}
						entries={featureEntries}
						invalid={invalidNames}
						onRename={(index, name) => cart.updateItemName(index, name)}
						onRemove={(index) => cart.removeItem(index)}
						{editingKey}
						currentKey={kwargsKey(buildFilterKwargs($state.snapshot(filterSelections), selectedDatasetDetail.filters, selectedOutcome))}
						onEdit={editVersion}
					/>
				{/if}

				<!-- What the output will hold: from the current filters for feature datasets,
				     and a placeholder for rasters until they're in the request -->
				<OutputSummary
						dataset={selectedDatasetDetail}
						isFeature={isFeature(selectedDatasetDetail)}
						features={isCustomMode ? ($customBoundary.featureCount ?? 0) : resolvedIds.length}
						boundaries={isCustomMode ? 1 : $selectionFcIds.length}
						extractTypes={rasterOptions.extractTypes}
						resources={rasterOptions.resources}
						{filterSelections}
						outcome={selectedOutcome}
						{saveState}
						empty={!isFeature(selectedDatasetDetail) && !inRequestNames.has(selectedDatasetDetail.name)}
					/>

				<!-- Configuration area: heading, then Reset, Add / Update and status -->
				<div class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 pt-4">
					<h3 class="text-base font-semibold">Select Dataset Options</h3>
					<DatasetActions
						isFeature={isFeature(selectedDatasetDetail)}
						{saveState}
						onAddToRequest={handleAddToRequest}
						mergeInto={mergeTarget}
						onUpdateRequest={handleUpdateRequest}
						onReset={handleReset}
					/>
				</div>
				{#if selectedDatasetDetail.processing_class === 'filter_and_agg' && selectedDatasetDetail.filters}
					<!-- Measure, Split results by, Filter records: one section each -->
					<div class="mt-4 space-y-4 pb-4">
					{#if selectedDatasetDetail.outcomes}
						<OutcomeSelector
							outcomes={selectedDatasetDetail.outcomes}
							selected={selectedOutcome}
							onSelect={(key) => {
								selectedOutcome = key;
								saveFeatureChoices();
							}}
						/>
					{/if}
					<FilterAndAggOptions
						filters={selectedDatasetDetail.filters}
						selections={filterSelections}
						onSelectionsChange={(s) => {
							filterSelections = s;
							saveFeatureChoices();
						}}
					/>
					</div>
				{:else}
					<RasterOptions
						dataset={selectedDatasetDetail}
						options={rasterOptions}
						onOptionsChange={handleRasterChange}
					/>
				{/if}
				<MoreOptionsHint scroller={optionsPane} />
			{/if}
		</div>
	</div>
</div>
