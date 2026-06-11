<svelte:head><title>GeoQuery - AidData</title></svelte:head>

<script lang="ts">
	import { get } from 'svelte/store';
	import { goto } from '$app/navigation';
	import { browser } from '$app/environment';
	import { currentStep } from '$lib/stores/ui';
	import { selection, type FCRef } from '$lib/stores/selection';
	import { cartCount } from '$lib/stores/cart';
	import { searchBoundaries, fetchFeatureIds, fetchDatasetsForFeatures, fetchBoundaryPresets, type BoundaryResult, type BoundaryPreset } from '$lib/api';
	import GeographySearch from '$lib/components/map/GeographySearch.svelte';
	import BoundaryBrowsePanel from '$lib/components/map/BoundaryBrowsePanel.svelte';
	import ZoomControls from '$lib/components/map/ZoomControls.svelte';
	import MapFrame, { type FcStyle } from '$lib/components/map/MapFrame.svelte';
	import { colorForIndex, lineWidthForLevel } from '$lib/utils/boundaryStyle';
	import WelcomeModal from '$lib/components/map/WelcomeModal.svelte';
	import CustomBoundaryPanel from '$lib/components/map/CustomBoundaryPanel.svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Tooltip from '$lib/components/ui/tooltip';
	import { PlusCircle, ArrowRight } from '@lucide/svelte';
	import { customBoundary } from '$lib/stores/customBoundary';
	import { bbox as turfBbox } from '@turf/bbox';

	// ── Local staged selection types ────────────────────────────────────────────
	// The map page edits a local "staged" selection. Nothing is written to the
	// store until the user confirms via "Find Data" in the selection panel.

	interface StagedSingleFC {
		mode: 'single';
		fc: FCRef;
		featureIds: number[];
	}
	interface StagedMultiFC {
		mode: 'multi';
		fcs: FCRef[];
	}
	type StagedSelection = StagedSingleFC | StagedMultiFC | null;

	// ── Initialise staged + bbox from the committed store on mount ───────────────
	function initFromStore(): { staged: StagedSelection; bbox: [number, number, number, number] | null } {
		const sel = get(selection);
		if (!sel) return { staged: null, bbox: null };
		if (sel.mode === 'single') {
			return {
				staged: { mode: 'single', fc: sel.fc, featureIds: [...sel.featureIds] },
				bbox: sel.fc.bbox ?? null
			};
		}
		const bboxes = sel.fcs.map((fc) => fc.bbox).filter(Boolean) as [number, number, number, number][];
		const bbox: [number, number, number, number] | null = bboxes.length
			? [
					Math.min(...bboxes.map((b) => b[0])),
					Math.min(...bboxes.map((b) => b[1])),
					Math.max(...bboxes.map((b) => b[2])),
					Math.max(...bboxes.map((b) => b[3]))
				]
			: null;
		return { staged: { mode: 'multi', fcs: [...sel.fcs] }, bbox };
	}

	// Don't restore a standard boundary if custom mode is active — the two are mutually exclusive
	const _init = get(customBoundary).active ? { staged: null, bbox: null } : initFromStore();

	$effect(() => {
		currentStep.set('map');
	});

	let allBoundaries = $state<BoundaryResult[]>([]);
	let boundaryPresets = $state<BoundaryPreset[]>([]);
	let boundaryLoading = $state(true);
	let boundaryLoadError = $state<string | null>(null);

	// Active tab in the selection panel. 'custom' mirrors customBoundary.active.
	type SelectionTab = 'explore' | 'browse' | 'custom';
	let activeTab = $state<SelectionTab>($customBoundary.active ? 'custom' : 'explore');

	function switchTab(tab: SelectionTab) {
		if (tab === 'custom') {
			// Activate custom mode; clear staged standard selection
			customBoundary.activate();
			selection.clear();
			staged = null;
			selectionModified = false;
			stagedNeedsConfirm = false;
			pendingBoundary = null;
			pendingFeatureIds = [];
			previewBoundaries = [];
		} else {
			// Leaving custom mode
			customBoundary.deactivate();
		}
		activeTab = tab;
	}

	/** Reset all boundary selection state and return to the Explore tab. */
	function resetAll() {
		staged = null;
		selectionModified = false;
		stagedNeedsConfirm = false;
		addingAnother = false;
		pendingBoundary = null;
		pendingFeatureIds = [];
		previewBoundaries = [];
		browseBoundaries = [];
		selection.clear();
		customBoundary.reset();
		activeTab = 'explore';
	}

	// Featured boundaries: tagged "featured", sorted by most recent, top 3
	let featuredBoundaries = $derived(
		allBoundaries
			.filter((b) => b.tags?.includes('featured'))
			.sort((a, b) => {
				const dateA = a.date_added ? new Date(a.date_added).getTime() : 0;
				const dateB = b.date_added ? new Date(b.date_added).getTime() : 0;
				return dateB - dateA;
			})
			.slice(0, 3)
	);

	$effect(() => {
		boundaryLoading = true;
		boundaryLoadError = null;
		Promise.all([
			searchBoundaries('', 0),
			fetchBoundaryPresets()
		]).then(([results, presets]) => {
			allBoundaries = results;
			boundaryPresets = presets;
		}).catch(() => {
			boundaryLoadError = 'Failed to load boundaries. Please refresh the page.';
		}).finally(() => {
			boundaryLoading = false;
		});
	});

	let showWelcome = $state(browser ? !sessionStorage.getItem('welcomeDismissed') : false);
	$effect(() => {
		if (!showWelcome && browser) sessionStorage.setItem('welcomeDismissed', '1');
	});

	let mapFrame: MapFrame;

	// Local staged selection (not yet committed to store)
	let staged = $state<StagedSelection>(_init.staged);
	// True when the user has picked a new boundary via GeographySearch since last commit
	let selectionModified = $state(false);

	// Browse/search shared selection state (synced between GeographySearch and BrowsePanel)
	let browseBoundaries = $state<BoundaryResult[]>([]);

	// Search preview state
	let pendingBoundary = $state<BoundaryResult | null>(null);
	let previewBoundaries = $state<BoundaryResult[]>([]); // Multi-boundary preview for map tiles
	let pendingFeatureIds = $state<number[]>([]);
	let currentBbox = $state<[number, number, number, number] | null>(_init.bbox);

	let userBbox = $derived.by(() => {
		if (!$customBoundary.active) return null;
		const fc = $customBoundary.finalFeatures;
		if (!fc || fc.features.length === 0) return null;
		try { return turfBbox(fc) as [number, number, number, number]; } catch { return null; }
	});
	let addingAnother = $state(false);

	// Async state
	let findingData = $state(false);
	// True when features have been changed post-commit; requires re-confirmation before Find Data
	let stagedNeedsConfirm = $state(false);

	// Running dataset count based on current staged coverage
	let datasetCount = $state<number | null>(null);
	let datasetCountLoading = $state(false);

	$effect(() => {
		const s = staged;
		if (!s) { datasetCount = null; datasetCountLoading = false; return; }

		datasetCountLoading = true;
		let cancelled = false;

		const timer = setTimeout(async () => {
			try {
				let ids: number[];
				if (s.mode === 'single') {
					ids = s.featureIds.length > 0 ? s.featureIds : await fetchFeatureIds([s.fc.id]);
				} else {
					ids = await fetchFeatureIds(s.fcs.map((fc) => fc.id));
				}
				if (cancelled) return;
				const datasets = await fetchDatasetsForFeatures(ids);
				if (!cancelled) { datasetCount = datasets.length; datasetCountLoading = false; }
			} catch {
				if (!cancelled) { datasetCount = null; datasetCountLoading = false; }
			}
		}, 400);

		return () => { cancelled = true; clearTimeout(timer); };
	});

	let hasIndividualFeatures = $derived(
		staged?.mode === 'single' && staged.featureIds.length > 0
	);

	// ── Derived map display values ───────────────────────────────────────────────

	let mapFcNames = $derived.by(() => {
		const names: string[] = [];
		if (staged?.mode === 'single') names.push(staged.fc.name);
		else if (staged?.mode === 'multi') names.push(...staged.fcs.map((fc) => fc.name));
		// Show preview tiles for multi-boundary selection (before commit)
		for (const b of previewBoundaries) {
			if (!names.includes(b.name)) names.push(b.name);
		}
		if (pendingBoundary && !names.includes(pendingBoundary.name))
			names.push(pendingBoundary.name);
		return names;
	});

	// Per-FC display styles: distinct color cycled by index, line width by ADM level.
	// Falls back gracefully for boundaries without a group_level.
	let mapFcStyles = $derived.by<FcStyle[]>(() => {
		return mapFcNames.map((name, idx) => {
			const meta = allBoundaries.find((b) => b.name === name);
			return {
				name,
				color: colorForIndex(idx),
				lineWidth: lineWidthForLevel(meta?.group_level)
			};
		});
	});

	// Pending boundary preview takes priority over the committed staged FC so
	// feature clicking is immediately available once a boundary is typed.
	let activeFcName = $derived.by(() => {
		if (pendingBoundary && !addingAnother) return pendingBoundary.name;
		if (staged?.mode === 'single') return staged.fc.name;
		return null;
	});

	let displaySelectedFeatureIds = $derived.by(() => {
		if (pendingBoundary && !addingAnother) return pendingFeatureIds;
		if (staged?.mode === 'single') return staged.featureIds;
		return [];
	});

	let stagedSummary = $derived.by(() => {
		if (!staged) return null;
		if (staged.mode === 'single') {
			const count = staged.featureIds.length;
			return {
				label: staged.fc.title ?? staged.fc.name,
				detail: count === 0 ? 'All features' : `${count} feature${count === 1 ? '' : 's'} selected`
			};
		}
		return {
			label: `${staged.fcs.length} collection${staged.fcs.length === 1 ? '' : 's'}`,
			detail: staged.fcs.map((fc) => fc.title ?? fc.name).join(', ')
		};
	});

	// ── Handlers ─────────────────────────────────────────────────────────────────

	function handleBrowseSelection(boundaries: BoundaryResult[]) {
		browseBoundaries = boundaries;
		handleSelect(boundaries);
	}

	function handleBrowsePanelSelection(selectedIds: Set<number>) {
		// Convert selected IDs from BrowsePanel back to BoundaryResult array
		const boundaries = allBoundaries.filter((b) => selectedIds.has(b.id));
		browseBoundaries = boundaries;
		handleSelect(boundaries);
	}

	function handleSelect(boundaries: BoundaryResult[]) {
		// When multiple boundaries are selected, clear feature-level selection since
		// feature selection only applies to single-boundary mode
		if (boundaries.length > 1) pendingFeatureIds = [];

		previewBoundaries = boundaries; // Store for map tile preview

		if (boundaries.length === 1) {
			pendingBoundary = boundaries[0];
			if (boundaries[0].bbox) currentBbox = boundaries[0].bbox;
		} else {
			pendingBoundary = null;
			// Calculate bbox union for multi-select
			const bboxes = boundaries.map((b) => b.bbox).filter(Boolean) as [number, number, number, number][];
			if (bboxes.length > 0) {
				currentBbox = [
					Math.min(...bboxes.map((b) => b[0])),
					Math.min(...bboxes.map((b) => b[1])),
					Math.max(...bboxes.map((b) => b[2])),
					Math.max(...bboxes.map((b) => b[3]))
				];
			}
		}
	}

	function handleProceed(boundaries: BoundaryResult[]) {
		// Use provided boundaries or fall back to browseBoundaries
		const selected = boundaries.length > 0 ? boundaries : browseBoundaries;

		// Convert BoundaryResults to FCRefs
		const fcs: FCRef[] = selected.map((b) => ({
			id: b.id,
			name: b.name,
			title: b.title,
			bbox: b.bbox ?? null
		}));

		if (addingAnother) {
			// When adding another boundary, merge into staged selection
			if (staged?.mode === 'single') {
				// Convert single-FC to multi-FC and add new boundaries
				staged = { mode: 'multi', fcs: [staged.fc, ...fcs] };
			} else if (staged?.mode === 'multi') {
				// Append to existing multi-FC, avoiding duplicates
				const existingIds = new Set(staged.fcs.map((f) => f.id));
				const newFcs = fcs.filter((f) => !existingIds.has(f.id));
				staged = { ...staged, fcs: [...staged.fcs, ...newFcs] };
			} else {
				// No prior staged selection
				staged = fcs.length === 1 ? { mode: 'single', fc: fcs[0], featureIds: [] } : { mode: 'multi', fcs };
			}
			addingAnother = false;
		} else {
			// Initial selection
			if (fcs.length === 1) {
				staged = { mode: 'single', fc: fcs[0], featureIds: [...pendingFeatureIds] };
			} else {
				staged = { mode: 'multi', fcs };
			}
		}

		selectionModified = true;
		stagedNeedsConfirm = false;
		pendingFeatureIds = [];
		pendingBoundary = null;
		previewBoundaries = [];
	}

	async function handleFindData() {
		if (!staged || findingData) return;
		await commitAndNavigate();
	}

	async function commitAndNavigate() {
		findingData = true;
		try {
			// Deactivate custom boundary mode when committing a standard boundary
			customBoundary.deactivate();

			// Write staged selection to the store
			selection.clear();
			if (staged!.mode === 'single') {
				selection.setSingleFC(staged!.fc);
				for (const id of staged!.featureIds) selection.toggleFeature(id);
			} else {
				selection.setSingleFC(staged!.fcs[0]);
				for (let i = 1; i < staged!.fcs.length; i++) selection.addFC(staged!.fcs[i]);
			}

			// Resolve flat Feature.id list for coverage checks and request submission
			const fcIds =
				staged!.mode === 'single'
					? [staged!.fc.id]
					: staged!.fcs.map((fc) => fc.id);
			const ids =
				staged!.mode === 'single' && staged!.featureIds.length > 0
					? staged!.featureIds
					: await fetchFeatureIds(fcIds);
			selection.setResolvedFeatureIds(ids);

			selectionModified = false;

			if (staged!.mode === 'single') {
				goto('/customize?selection');
			} else {
				goto(`/customize?fc=${staged!.fcs.map((fc) => fc.id).join(',')}`);
			}
		} catch (err) {
			console.error('Failed to commit selection:', err);
		} finally {
			findingData = false;
		}
	}

	function handleFeatureClick(featureId: number) {
		if (pendingBoundary && !addingAnother) {
			pendingFeatureIds = pendingFeatureIds.includes(featureId)
				? pendingFeatureIds.filter((id) => id !== featureId)
				: [...pendingFeatureIds, featureId];
		} else if (staged?.mode === 'single') {
			const ids = staged.featureIds;
			staged = {
				...staged,
				featureIds: ids.includes(featureId)
					? ids.filter((id) => id !== featureId)
					: [...ids, featureId]
			};
			selectionModified = true;
			stagedNeedsConfirm = true;
		}
	}

	function handleZoomIn() {
		mapFrame?.zoomIn();
	}

	function handleZoomOut() {
		mapFrame?.zoomOut();
	}
</script>

<WelcomeModal bind:open={showWelcome} />

<div class="relative flex h-[calc(100vh-8rem)] flex-col">
	<!-- Left panel: search + selection status -->
	<div class="absolute left-4 top-4 bottom-4 z-10 w-96 max-w-[calc(100vw-2rem)] space-y-2 flex flex-col">

		{#if staged && !addingAnother && !$customBoundary.active}
			<!-- Staged selection summary (shown when there's a committed selection) -->
			<div class="rounded-lg border bg-card p-4 shadow-lg">
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<p class="truncate font-semibold">{stagedSummary?.label}</p>
						<p class="text-sm text-muted-foreground">{stagedSummary?.detail}</p>
						<p class="mt-0.5 text-xs text-muted-foreground">
							{#if datasetCountLoading}
								Checking coverage…
							{:else if datasetCount !== null}
								<strong>{datasetCount}</strong> dataset{datasetCount === 1 ? '' : 's'} available
							{/if}
						</p>
					</div>
					<Button
						size="sm"
						variant="ghost"
						onclick={resetAll}
						class="shrink-0 text-muted-foreground hover:text-destructive"
					>
						Restart
					</Button>
				</div>

				{#if staged.mode === 'single'}
					<p class="mt-2 text-xs text-muted-foreground">
						Click features on the map to sub-select, or leave all to use the entire collection.
					</p>
				{/if}

				{#if selectionModified && $cartCount > 0}
					<p class="mt-2 text-xs text-amber-700 dark:text-amber-400">
						Your selection has changed. Actual dataset coverage may vary across selected features.
					</p>
				{/if}

				<div class="mt-3 flex gap-2">
					{#if !hasIndividualFeatures && !stagedNeedsConfirm}
						<Button
							size="sm"
							variant="outline"
							onclick={() => {
								addingAnother = true;
								pendingBoundary = null;
								// Re-hydrate browseBoundaries from staged so chips and dedup work
								const stagedIds = new Set(
									staged?.mode === 'single'
										? [staged.fc.id]
										: (staged?.fcs.map((f) => f.id) ?? [])
								);
								browseBoundaries = allBoundaries.filter((b) => stagedIds.has(b.id));
							}}
						>
							<PlusCircle class="mr-1 h-3.5 w-3.5" />
							Add Boundary
						</Button>
					{/if}
					{#if stagedNeedsConfirm && staged?.mode === 'single'}
						<Button
							size="sm"
							class="flex-1"
							onclick={() => { stagedNeedsConfirm = false; }}
						>
							{staged.featureIds.length > 0 ? 'Save Selected' : 'Save All'}
							<ArrowRight class="ml-1 h-3.5 w-3.5" />
						</Button>
					{:else}
						<Button size="sm" class="flex-1" disabled={findingData} onclick={handleFindData}>
							{findingData ? 'Loading…' : 'Find Data'}
							{#if !findingData}<ArrowRight class="ml-1 h-3.5 w-3.5" />{/if}
						</Button>
					{/if}
				</div>
			</div>
		{:else}
			<!-- Tabbed selection card -->
			<div class="rounded-lg border bg-card shadow-lg flex flex-col min-h-0">
				<div class="p-4 pb-2 shrink-0">
					<div class="flex items-start justify-between gap-2 mb-3">
						<h2 class="text-lg font-semibold text-primary">
							Select Boundaries to Begin
						</h2>
						{#if browseBoundaries.length > 0 || $customBoundary.fileName || $customBoundary.active}
							<Button
								size="sm"
								variant="ghost"
								onclick={resetAll}
								class="shrink-0 text-xs text-muted-foreground hover:text-destructive -mr-1 -mt-1"
							>
								Restart
							</Button>
						{/if}
					</div>
					<!-- Tabs -->
					<div class="grid grid-cols-3 gap-1 rounded-md bg-muted p-1">
						<button
							class="rounded px-2 py-1.5 text-xs font-medium transition-colors {activeTab === 'explore' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}"
							onclick={() => switchTab('explore')}
						>
							Explore
						</button>
						<button
							class="rounded px-2 py-1.5 text-xs font-medium transition-colors {activeTab === 'browse' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}"
							onclick={() => switchTab('browse')}
						>
							Browse All
						</button>
						<button
							class="rounded px-2 py-1.5 text-xs font-medium transition-colors {activeTab === 'custom' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}"
							onclick={() => switchTab('custom')}
						>
							Custom
						</button>
					</div>
				</div>

				<!-- Tab content (scrolls if too tall; explore tab needs overflow-visible so its dropdown isn't clipped) -->
				<div class="px-4 pb-4 pt-2 min-h-0 flex-1 {activeTab === 'explore' ? 'overflow-visible' : 'overflow-y-auto'}">
					{#if activeTab === 'explore'}
						<GeographySearch
							featuredBoundaries={addingAnother ? [] : featuredBoundaries}
							selectedBoundaries={browseBoundaries}
							proceedLabel={browseBoundaries.length === 1 && pendingFeatureIds.length > 0
								? 'Save Selected Features'
								: 'Find Data'}
							proceedTooltip={browseBoundaries.length > 1 && pendingFeatureIds.length > 0
								? 'Individual feature selections are limited to one boundary collection.'
								: undefined}
							onSelect={handleBrowseSelection}
							onProceed={handleProceed}
						/>

						<!-- Feature-selection hint once a single boundary is selected -->
						{#if browseBoundaries.length === 1 && !addingAnother}
							<div class="mt-3 rounded-md border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
								{#if pendingFeatureIds.length === 0}
									Click features on the map to narrow your selection, then press
									<strong>Save Selected Features</strong>. Or press <strong>Find Data</strong> to use
									the entire collection.
								{:else}
									<strong>{pendingFeatureIds.length}</strong>
									{pendingFeatureIds.length === 1 ? 'feature' : 'features'} selected — click more to
									add, or click a selected feature to deselect it.
								{/if}
							</div>
						{/if}
					{:else if activeTab === 'browse'}
						{#if boundaryLoadError}
							<p class="text-sm text-destructive py-2">{boundaryLoadError}</p>
						{:else}
							<BoundaryBrowsePanel
								allBoundaries={allBoundaries}
								selectedIds={new Set(browseBoundaries.map((b) => b.id))}
								presets={boundaryPresets}
								onSelectionChange={handleBrowsePanelSelection}
								loading={boundaryLoading}
							/>
						{/if}

						{#if browseBoundaries.length > 0}
							<div class="mt-4 pt-3 border-t flex justify-end">
								<Button size="sm" onclick={() => handleProceed(browseBoundaries)}>
									Find Data
									<ArrowRight class="ml-1 h-4 w-4" />
								</Button>
							</div>
						{/if}
					{:else if activeTab === 'custom'}
						<CustomBoundaryPanel />
					{/if}
				</div>

				<!-- Cancel "addingAnother" footer -->
				{#if addingAnother}
					<div class="shrink-0 border-t px-4 py-2">
						<button
							class="text-xs text-muted-foreground underline hover:text-foreground"
							onclick={() => { addingAnother = false; pendingBoundary = null; previewBoundaries = []; }}
						>
							Cancel adding another boundary
						</button>
					</div>
				{/if}
			</div>
		{/if}
	</div>

	<!-- Zoom Controls -->
	<div class="absolute right-4 top-4 z-10">
		<ZoomControls onZoomIn={handleZoomIn} onZoomOut={handleZoomOut} />
	</div>

	<!-- Map -->
	<MapFrame
		bind:this={mapFrame}
		class="flex-1"
		fcStyles={$customBoundary.active ? [] : mapFcStyles}
		activeFcName={$customBoundary.active ? null : activeFcName}
		selectedFeatureIds={$customBoundary.active ? [] : displaySelectedFeatureIds}
		bbox={userBbox ?? currentBbox}
		onFeatureClick={handleFeatureClick}
		userGeoJSON={$customBoundary.active ? $customBoundary.finalFeatures : null}
	/>
</div>
