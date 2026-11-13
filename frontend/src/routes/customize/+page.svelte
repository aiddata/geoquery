<script lang="ts">
	import Seo from '#lib/components/layout/Seo.svelte';
	import { get } from 'svelte/store';
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { currentStep } from '#lib/stores/ui.js';
	import { cart, type CartItem } from '#lib/stores/cart.js';
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
	import SelectionSummary from '#lib/components/datasets/SelectionSummary.svelte';
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

	// Choices made for a dataset but not yet added to the request, keyed by
	// dataset name. Switching to another dataset keeps them here, so coming
	// back restores them instead of starting over; adding or resetting clears
	// them. Datasets with an entry (or the open one with choices) get the
	// "open" dot in the list.
	type Draft = {
		rasterOptions: { extractTypes: string[]; resources: string[] };
		filterSelections: Record<string, FilterSelection>;
		selectedOutcome: string;
	};
	let drafts = $state<Record<string, Draft>>({});

	function defaultOutcome(detail: DatasetDetail): string {
		return detail.outcomes ? (Object.keys(detail.outcomes)[0] ?? '') : '';
	}

	// Whether the open dataset has choices worth keeping. Feature datasets
	// start with every filter selected, so for them it means "changed from
	// the defaults".
	const currentHasChoices = $derived.by(() => {
		const detail = selectedDatasetDetail;
		if (!detail) return false;
		if (detail.processing_class === 'filter_and_agg' && detail.filters) {
			return (
				JSON.stringify(filterSelections) !== JSON.stringify(initFilterSelections(detail.filters)) ||
				selectedOutcome !== defaultOutcome(detail)
			);
		}
		return rasterOptions.extractTypes.length > 0 || rasterOptions.resources.length > 0;
	});

	const openDatasetNames = $derived.by(() => {
		const names = new Set(Object.keys(drafts));
		const current = selectedDatasetDetail?.name;
		if (current) {
			if (currentHasChoices) names.add(current);
			else names.delete(current);
		}
		return names;
	});

	function saveDraft() {
		const name = selectedDatasetDetail?.name;
		if (!name) return;
		if (currentHasChoices) {
			drafts[name] = {
				rasterOptions: { extractTypes: [...rasterOptions.extractTypes], resources: [...rasterOptions.resources] },
				filterSelections: structuredClone($state.snapshot(filterSelections)),
				selectedOutcome
			};
		} else {
			delete drafts[name];
		}
	}

	$effect(() => {
		const detail = selectedDatasetDetail;
		// Read without tracking: saving a draft must not re-run this.
		const draft = detail ? untrack(() => drafts[detail.name]) : undefined;
		if (detail?.processing_class === 'filter_and_agg' && detail.filters) {
			filterSelections = draft
				? structuredClone($state.snapshot(draft.filterSelections))
				: initFilterSelections(detail.filters);
		}
		selectedOutcome = detail ? (draft?.selectedOutcome ?? defaultOutcome(detail)) : '';
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
		saveDraft();
		// Drop the old detail now, so nothing can save the next dataset's
		// choices under the previous name while its detail loads.
		selectedDatasetDetail = null;
		selectedDatasetSummary = dataset;
		const draft = drafts[dataset.name];
		rasterOptions = draft
			? { extractTypes: [...draft.rasterOptions.extractTypes], resources: [...draft.rasterOptions.resources] }
			: { extractTypes: [], resources: [] };
	}

	function handleAddToRequest(customName: string) {
		if (!selectedDatasetDetail) return;

		const isFilterAndAgg = selectedDatasetDetail.processing_class === 'filter_and_agg';

		const item: CartItem = {
			customName: customName || selectedDatasetDetail.title || selectedDatasetDetail.name,
			datasetName: selectedDatasetDetail.name,
			datasetTitle: selectedDatasetDetail.title ?? selectedDatasetDetail.name,
			datasetType: selectedDatasetDetail.type,
			processingClass: selectedDatasetDetail.processing_class,
			...(isFilterAndAgg
				? {
					filterSelections: { ...filterSelections },
					kwargs: buildFilterKwargs(filterSelections, selectedDatasetDetail.filters, selectedOutcome),
				}
				: {
					extractTypes: [...rasterOptions.extractTypes],
					resources: [...rasterOptions.resources],
					resourceLabels: rasterOptions.resources.map((name) => {
						const res = selectedDatasetDetail!.resources.find((r) => r.name === name);
						return res?.label ?? res?.temporal ?? name;
					}),
				}),
		};

		cart.upsertItem(item);
		delete drafts[item.datasetName];

		// Reset for next selection
		selectedDatasetSummary = null;
		selectedDatasetDetail = null;
		rasterOptions = { extractTypes: [], resources: [] };
		filterSelections = {};
	}

	function handleReset() {
		if (selectedDatasetDetail) delete drafts[selectedDatasetDetail.name];
		if (selectedDatasetDetail?.processing_class === 'filter_and_agg' && selectedDatasetDetail.filters) {
			filterSelections = initFilterSelections(selectedDatasetDetail.filters);
			if (selectedDatasetDetail.outcomes) {
				selectedOutcome = Object.keys(selectedDatasetDetail.outcomes)[0] ?? '';
			}
		} else {
			rasterOptions = { extractTypes: [], resources: [] };
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
		<!-- Three-panel layout (min-width enforced; scrolls horizontally on narrow screens) -->
		<div class="flex flex-1 overflow-hidden">
			<!-- Left Panel: Dataset Selector -->
			<div class="flex h-full w-80 shrink-0 flex-col overflow-hidden border-r bg-card">
				<DatasetSelector
					{datasets}
					{categories}
					selectedDataset={selectedDatasetSummary}
					onSelect={handleDatasetSelect}
					{outOfRangeNames}
					openNames={openDatasetNames}
				/>
			</div>

			<!-- Center Panel: Dataset Configuration. Scrolls vertically only. -->
			<div class="min-w-0 flex-1 overflow-y-auto overflow-x-hidden bg-background">
				{#if !selectedDatasetDetail && !detailLoading}
					<div class="flex h-full items-center justify-center">
						<p class="text-muted-foreground">
							{selectedDatasetSummary
								? 'Loading dataset configuration...'
								: 'Select a dataset from the list to configure it.'}
						</p>
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

					<!-- Configuration area -->
					<h3 class="px-4 pt-4 text-base font-semibold">Select Dataset Options</h3>
					{#if selectedDatasetDetail.processing_class === 'filter_and_agg' && selectedDatasetDetail.filters}
						{#if selectedDatasetDetail.outcomes}
							<OutcomeSelector
								outcomes={selectedDatasetDetail.outcomes}
								selected={selectedOutcome}
								onSelect={(key) => (selectedOutcome = key)}
							/>
						{/if}
						<FilterAndAggOptions
							filters={selectedDatasetDetail.filters}
							selections={filterSelections}
							onSelectionsChange={(s) => (filterSelections = s)}
						/>
					{:else}
						<RasterOptions
							dataset={selectedDatasetDetail}
							options={rasterOptions}
							onOptionsChange={(o) => (rasterOptions = o)}
						/>
					{/if}
				{/if}
			</div>

			<!-- Right Panel: Selection Summary -->
			<div class="flex h-full w-72 shrink-0 flex-col overflow-hidden border-l bg-card">
				<SelectionSummary
					dataset={selectedDatasetDetail}
					extractTypes={selectedDatasetDetail?.processing_class === 'filter_and_agg' ? undefined : rasterOptions.extractTypes}
					selectedResources={selectedDatasetDetail?.processing_class === 'filter_and_agg' ? undefined : rasterOptions.resources}
					filterSelections={selectedDatasetDetail?.processing_class === 'filter_and_agg' ? filterSelections : undefined}
					onAddToRequest={handleAddToRequest}
					onReset={handleReset}
					hasChoices={currentHasChoices}
				/>
			</div>
		</div>
	{/if}
</div>
