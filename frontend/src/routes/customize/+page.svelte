<script lang="ts">
	import { get } from 'svelte/store';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { currentStep } from '$lib/stores/ui';
	import { cart, type CartItem } from '$lib/stores/cart';
	import {
		selection,
		selectionFcIds,
		selectedFeatureIds,
		type FCRef
	} from '$lib/stores/selection';
	import {
		fetchDatasetsForFeatures,
		fetchDatasetDetail,
		fetchDatasetCategories,
		fetchFeatureIds,
		type DatasetSummary,
		type DatasetDetail,
		type DatasetCategory
	} from '$lib/api';
	import DatasetSelector from '$lib/components/datasets/DatasetSelector.svelte';
	import RasterOptions from '$lib/components/datasets/RasterOptions.svelte';
	import SelectionSummary from '$lib/components/datasets/SelectionSummary.svelte';
	import { Button } from '$lib/components/ui/button';
	import { ChevronLeft, ArrowRight } from '@lucide/svelte';
	import { cartCount } from '$lib/stores/cart';

	$effect(() => {
		currentStep.set('search');
	});

	// Determine selection mode from URL params
	let isSingleMode = $derived(page.url.searchParams.has('selection'));
	let isMultiMode = $derived(!!page.url.searchParams.get('fc'));

	// Validate selection against the store; redirect to map if stale/missing
	$effect(() => {
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
		if ($selection?.mode === 'single') return $selection.fc.title ?? $selection.fc.name;
		if ($selection?.mode === 'multi')
			return $selection.fcs.map((fc) => fc.title ?? fc.name).join(', ');
		return '';
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

	// Raster options state
	let rasterOptions = $state<{ extractTypes: string[]; resources: string[] }>({
		extractTypes: [],
		resources: []
	});

	// Fetch datasets when resolved feature IDs become available
	$effect(() => {
		const ids = resolvedIds;
		if (!ids.length) return;

		loadError = null;

		Promise.all([fetchDatasetsForFeatures(ids), fetchDatasetCategories()])
			.then(([ds, cats]) => {
				datasets = ds;
				categories = cats;
				const covered = new Set(ds.map((d) => d.name));
				const current = get(cart);
				if (current.length > 0) {
					cart.setItems(current.filter((item) => covered.has(item.datasetName)));
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
		selectedDatasetSummary = dataset;
		// Reset configuration state
		releaseFilters = {};
		rasterOptions = { extractTypes: [], resources: [] };
	}

	function handleAddToRequest(customName: string) {
		if (!selectedDatasetDetail) return;

		const item: CartItem = {
			customName: customName || selectedDatasetDetail.title || selectedDatasetDetail.name,
			datasetName: selectedDatasetDetail.name,
			datasetTitle: selectedDatasetDetail.title ?? selectedDatasetDetail.name,
			datasetType: selectedDatasetDetail.type,
			extractTypes: [...rasterOptions.extractTypes],
			resources: [...rasterOptions.resources],
			resourceLabels: rasterOptions.resources.map((name) => {
				const res = selectedDatasetDetail!.resources.find((r) => r.name === name);
				return res?.label ?? res?.temporal ?? name;
			}),
		};

		cart.upsertItem(item);

		// Reset for next selection
		selectedDatasetSummary = null;
		selectedDatasetDetail = null;
		releaseFilters = {};
		rasterOptions = { extractTypes: [], resources: [] };
	}

	function handleReset() {
		rasterOptions = { extractTypes: [], resources: [] };
	}
</script>

<div class="flex h-[calc(100vh-7rem)] flex-col">
	<!-- Top bar with back navigation and selection info -->
	<div class="flex items-center gap-3 border-b bg-muted/30 px-4 py-2">
		<Button variant="ghost" size="sm" onclick={() => goto('/')}>
			<ChevronLeft class="mr-1 h-4 w-4" />
			Back to Map
		</Button>
		<span class="text-sm text-muted-foreground">|</span>
		<span class="truncate text-sm">
			<strong>{selectionLabel || 'No selection'}</strong>
		</span>

		{#if $cartCount > 0}
			<div class="ml-auto">
				<Button size="sm" href="/review">
					Review Request ({$cartCount})
					<ArrowRight class="ml-1 h-4 w-4" />
				</Button>
			</div>
		{/if}
	</div>

	{#if !resolvedIds.length}
		<!-- Waiting for feature IDs to resolve -->
		<div class="flex flex-1 items-center justify-center">
			<p class="text-muted-foreground">Loading available datasets…</p>
		</div>
	{:else if loadError}
		<!-- Error state -->
		<div class="flex flex-1 items-center justify-center">
			<div class="max-w-md text-center">
				<p class="text-lg font-medium text-destructive">Failed to load datasets</p>
				<p class="mt-2 text-sm text-muted-foreground">{loadError}</p>
			</div>
		</div>
	{:else}
		<!-- Three-panel layout -->
		<div class="flex flex-1 overflow-hidden">
			<!-- Left Panel: Dataset Selector -->
			<div class="w-80 shrink-0 border-r bg-card">
				<DatasetSelector
					{datasets}
					{categories}
					selectedDataset={selectedDatasetSummary}
					onSelect={handleDatasetSelect}
				/>
			</div>

			<!-- Center Panel: Dataset Configuration -->
			<div class="flex-1 overflow-auto bg-background">
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
						<h2 class="font-semibold">
							{selectedDatasetDetail.title ?? selectedDatasetDetail.name}
						</h2>
						{#if selectedDatasetDetail.description}
							<p class="mt-1 text-sm text-muted-foreground">
								{selectedDatasetDetail.description}
							</p>
						{/if}
					</div>

					<!-- Configuration area -->
					<RasterOptions
						dataset={selectedDatasetDetail}
						options={rasterOptions}
						onOptionsChange={(o) => (rasterOptions = o)}
					/>
				{/if}
			</div>

			<!-- Right Panel: Selection Summary -->
			<div class="w-72 shrink-0 border-l bg-card">
				<SelectionSummary
					dataset={selectedDatasetDetail}
					extractTypes={rasterOptions.extractTypes}
					selectedResources={rasterOptions.resources}
					onAddToRequest={handleAddToRequest}
					onReset={handleReset}
				/>
			</div>
		</div>
	{/if}
</div>
