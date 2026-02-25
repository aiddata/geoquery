<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { currentStep } from '$lib/stores/ui';
	import { cart, type CartItem } from '$lib/stores/cart';
	import {
		fetchDatasetsForBoundary,
		fetchDatasetDetail,
		fetchDatasetCategories,
		type DatasetSummary,
		type DatasetDetail,
		type DatasetCategory
	} from '$lib/api';
	import DatasetSelector from '$lib/components/datasets/DatasetSelector.svelte';
	import ReleaseFilters from '$lib/components/datasets/ReleaseFilters.svelte';
	import RasterOptions from '$lib/components/datasets/RasterOptions.svelte';
	import SelectionSummary from '$lib/components/datasets/SelectionSummary.svelte';
	import { Button } from '$lib/components/ui/button';
	import { ChevronLeft } from '@lucide/svelte';

	$effect(() => {
		currentStep.set('search');
	});

	// Read boundary from URL query params
	let boundaryName = $derived(page.url.searchParams.get('boundary') ?? '');

	// Data loading state
	let datasets = $state<DatasetSummary[]>([]);
	let categories = $state<DatasetCategory[]>([]);
	let loadError = $state<string | null>(null);

	// Currently selected dataset (summary from the list)
	let selectedDatasetSummary = $state<DatasetSummary | null>(null);
	// Full detail for the selected dataset
	let selectedDatasetDetail = $state<DatasetDetail | null>(null);
	let detailLoading = $state(false);

	// Release filter state
	let releaseFilters = $state<Record<string, string[]>>({});

	// Raster options state
	let rasterOptions = $state<{ extractTypes: string[]; resources: string[] }>({
		extractTypes: [],
		resources: []
	});

	// Fetch datasets and categories when boundary changes
	$effect(() => {
		if (!boundaryName) return;

		loadError = null;

		Promise.all([fetchDatasetsForBoundary(boundaryName), fetchDatasetCategories()])
			.then(([ds, cats]) => {
				datasets = ds;
				categories = cats;
			})
			.catch((err) => {
				loadError = err.message;
				console.error('Failed to load datasets:', err);
			});
	});

	// Fetch full detail when a dataset is selected
	$effect(() => {
		if (!selectedDatasetSummary || !boundaryName) {
			selectedDatasetDetail = null;
			return;
		}

		detailLoading = true;
		fetchDatasetDetail(selectedDatasetSummary.name, boundaryName)
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

		const isRelease = selectedDatasetDetail.type === 'release';
		const summaryParts = [`${selectedDatasetDetail.title ?? selectedDatasetDetail.name}`];
		summaryParts.push(`within ${boundaryName}`);

		const item: CartItem = {
			customName: customName || selectedDatasetDetail.title || selectedDatasetDetail.name,
			boundaryName,
			datasetName: selectedDatasetDetail.name,
			datasetTitle: selectedDatasetDetail.title ?? selectedDatasetDetail.name,
			datasetType: selectedDatasetDetail.type,
			summary: summaryParts.join(' ')
		};

		if (isRelease) {
			item.filters = { ...releaseFilters };
		} else {
			item.extractTypes = [...rasterOptions.extractTypes];
			item.resources = [...rasterOptions.resources];
		}

		cart.addItem(item);

		// Reset for next selection
		selectedDatasetSummary = null;
		selectedDatasetDetail = null;
		releaseFilters = {};
		rasterOptions = { extractTypes: [], resources: [] };
	}

	function handleReset() {
		releaseFilters = {};
		rasterOptions = { extractTypes: [], resources: [] };
	}
</script>

<div class="flex h-[calc(100vh-7rem)] flex-col">
	<!-- Top bar with back navigation and boundary info -->
	<div class="flex items-center gap-3 border-b bg-muted/30 px-4 py-2">
		<Button variant="ghost" size="sm" onclick={() => goto('/')}>
			<ChevronLeft class="mr-1 h-4 w-4" />
			Back to Map
		</Button>
		<span class="text-sm text-muted-foreground">|</span>
		<span class="text-sm">
			Boundary: <strong>{boundaryName || 'None selected'}</strong>
		</span>
	</div>

	{#if !boundaryName}
		<!-- No boundary selected -->
		<div class="flex flex-1 items-center justify-center">
			<div class="text-center">
				<p class="text-lg text-muted-foreground">No boundary selected.</p>
				<Button variant="link" onclick={() => goto('/')}>Go back to select a boundary</Button>
			</div>
		</div>
	{:else if loadError}
		<!-- Error state -->
		<div class="flex flex-1 items-center justify-center">
			<div class="max-w-md text-center">
				<p class="text-lg font-medium text-destructive">Failed to load datasets</p>
				<p class="mt-2 text-sm text-muted-foreground">{loadError}</p>
				<p class="mt-4 text-xs text-muted-foreground">
					The backend endpoint <code class="rounded bg-muted px-1 py-0.5">GET /api/datasets/</code>
					needs to be implemented.
				</p>
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
					{#if selectedDatasetDetail.type === 'release'}
						<ReleaseFilters
							dataset={selectedDatasetDetail}
							filters={releaseFilters}
							onFiltersChange={(f) => (releaseFilters = f)}
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
			<div class="w-72 shrink-0 border-l bg-card">
				<SelectionSummary
					{boundaryName}
					dataset={selectedDatasetDetail}
					filters={selectedDatasetDetail?.type === 'release' ? releaseFilters : undefined}
					extractTypes={selectedDatasetDetail?.type !== 'release'
						? rasterOptions.extractTypes
						: undefined}
					selectedResources={selectedDatasetDetail?.type !== 'release'
						? rasterOptions.resources
						: undefined}
					onAddToRequest={handleAddToRequest}
					onReset={handleReset}
				/>
			</div>
		</div>
	{/if}
</div>
