<script lang="ts">
	import Seo from '#lib/components/layout/Seo.svelte';
	import { get } from 'svelte/store';
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { currentStep } from '#lib/stores/ui.js';
	import { cart, type CartItem } from '#lib/stores/cart.js';
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
	import { TriangleAlert } from '@lucide/svelte';
	import DatasetMetadata from '#lib/components/datasets/DatasetMetadata.svelte';
	import DatasetSelector from '#lib/components/datasets/DatasetSelector.svelte';
	import RasterOptions from '#lib/components/datasets/RasterOptions.svelte';
	import FilterAndAggOptions from '#lib/components/datasets/FilterAndAggOptions.svelte';
	import OutcomeSelector from '#lib/components/datasets/OutcomeSelector.svelte';
	import DatasetActions from '#lib/components/datasets/DatasetActions.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { ChevronLeft, ArrowRight } from '@lucide/svelte';
	import { cartCount } from '#lib/stores/cart.js';

	$effect(() => {
		currentStep.set('search');
	});

	// Determine selection mode from URL params
	let isSingleMode = $derived(page.url.searchParams.has('selection'));
	let isMultiMode = $derived(!!page.url.searchParams.get('fc'));
	let isCustomMode = $derived($customBoundary.saved && $customBoundary.active);

	// Validate selection against the store; redirect to map if stale/missing
	$effect(() => {
		if (isCustomMode) return;
		if (isSingleMode && $selection?.mode !== 'single') goto('/');
		else if (isMultiMode && $selection?.mode !== 'multi') goto('/');
		else if (!isSingleMode && !isMultiMode) goto('/');
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

	// Human-readable label for the top bar
	let selectionLabel = $derived.by(() => {
		if (isCustomMode) return $customBoundary.fileName || 'Custom boundary';
		if ($selection?.mode === 'single')
			return $selection.fc.short_name ?? $selection.fc.title ?? $selection.fc.name;
		if ($selection?.mode === 'multi') {
			const names = $selection.fcs.map((fc) => fc.short_name ?? fc.title ?? fc.name);
			if (names.length <= 2) return names.join(', ');
			const rest = names.length - 2;
			return `${names[0]}, ${names[1]}, and ${rest} other${rest > 1 ? 's' : ''}`;
		}
		return '';
	});

	let selectionTooltip = $derived.by(() => {
		if ($selection?.mode === 'multi' && $selection.fcs.length > 2)
			return $selection.fcs.map((fc) => fc.title ?? fc.name).join('\n');
		return '';
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
	const featureSaved = $derived(
		!!currentKwargs &&
			$cart.some(
				(i) => i.datasetName === selectedDatasetDetail?.name && kwargsKey(i.kwargs) === kwargsKey(currentKwargs)
			)
	);

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
			if (!$cart.some((i) => i.datasetName === name && kwargsKey(i.kwargs) === key)) names.add(name);
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

		const datasetPromise = custom ? fetchAllDatasets() : fetchDatasetsForFeatures(ids);

		Promise.all([datasetPromise, fetchDatasetCategories()])
			.then(([ds, cats]) => {
				datasets = ds;
				categories = cats;
				if (!custom) {
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
			customName: detail.title ?? detail.name,
			datasetName: detail.name,
			datasetTitle: detail.title ?? detail.name,
			datasetType: detail.type,
			processingClass: detail.processing_class,
			filterSelections: selections,
			kwargs: buildFilterKwargs(selections, detail.filters, selectedOutcome)
		};
	}

	/** Leave edit mode: the filters stay, but no longer replace an entry. */
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
</script>

<Seo title="Customize Datasets" description="Browse GeoQuery's datasets, including population, nighttime lights, climate, land cover, conflict and health, and choose the years and statistics to extract for your boundaries." />

<div class="flex h-[calc(100vh-8rem)] flex-col">
	<!-- Top bar with back navigation and selection info -->
	<div class="flex items-center gap-3 border-b bg-muted/30 px-4 py-2">
		<Button variant="ghost" size="sm" onclick={() => goto('/')}>
			<ChevronLeft />
			Back to Map
		</Button>
		<span class="text-sm text-muted-foreground">|</span>
		<span class="truncate text-sm" title={selectionTooltip || undefined}>
			<strong>{selectionLabel || 'No selection'}</strong>
		</span>

		{#if $cartCount > 0}
			<div class="ml-auto">
				<Button size="sm" href="/review">
					Review Request ({$cartCount})
					<ArrowRight />
				</Button>
			</div>
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

	{#if !resolvedIds.length && !isCustomMode}
		<!-- Waiting for feature IDs to resolve -->
		<div class="flex flex-1 items-center justify-center">
			<p class="text-muted-foreground">Loading available datasets…</p>
		</div>
	{:else if loadError}
		<!-- Error state -->
		<div class="flex flex-1 items-center justify-center">
			<div class="max-w-md text-center">
				<p class="text-lg font-bold text-destructive">Failed to load datasets</p>
				<p class="mt-2 text-sm text-muted-foreground">{loadError}</p>
			</div>
		</div>
	{:else}
		<!-- Two-panel layout: dataset list and the open dataset (min-width enforced) -->
		<div class="flex flex-1 overflow-hidden">
			<!-- Left Panel: Dataset Selector -->
			<div class="flex h-full w-80 shrink-0 flex-col overflow-hidden border-r bg-card">
				<DatasetSelector
					{datasets}
					{categories}
					selectedDataset={selectedDatasetSummary}
					onSelect={handleDatasetSelect}
					{outOfRangeNames}
					{inRequestNames}
					{unsavedNames}
				/>
			</div>

			<!-- Center Panel: Dataset Configuration. Scrolls vertically only. -->
			<div class="min-w-0 flex-1 overflow-y-auto overflow-x-hidden bg-background">
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

					<!-- Configuration area: heading, then Reset, Add / Update and status -->
					<div class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 pt-4">
						<h3 class="text-base font-semibold">Select Dataset Options</h3>
						<DatasetActions
							dataset={selectedDatasetDetail}
							isFeature={isFeature(selectedDatasetDetail)}
							extractTypes={rasterOptions.extractTypes}
							selectedResources={rasterOptions.resources}
							{saveState}
							onAddToRequest={handleAddToRequest}
							onUpdateRequest={handleUpdateRequest}
							onReset={handleReset}
						/>
					</div>
					{#if selectedDatasetDetail.processing_class === 'filter_and_agg' && selectedDatasetDetail.filters}
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
					{:else}
						<RasterOptions
							dataset={selectedDatasetDetail}
							options={rasterOptions}
							onOptionsChange={handleRasterChange}
						/>
					{/if}
				{/if}
			</div>
		</div>
	{/if}
</div>
