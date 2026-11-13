<Seo />
<svelte:head>
	<!-- Static content only, so it can't contain a closing script tag -->
	{@html `<script type="application/ld+json">${JSON.stringify(APP_JSON_LD)}</script>`}
</svelte:head>

<script lang="ts">
	import Seo from '#lib/components/layout/Seo.svelte';
	import { APP_JSON_LD } from '#lib/seo.js';
	import { get } from 'svelte/store';
	import { onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { browser } from '$app/env';
	import { currentStep } from '#lib/stores/ui.js';
	import { selection, type FCRef } from '#lib/stores/selection.js';
	import { cartCount } from '#lib/stores/cart.js';
	import { searchBoundaries, fetchFeatureIds, fetchDatasetsForFeatures, fetchBoundaryPresets, type BoundaryResult, type BoundaryPreset } from '#lib/api.js';
	import GeographySearch from '#lib/components/map/GeographySearch.svelte';
	import BoundaryBrowsePanel from '#lib/components/map/BoundaryBrowsePanel.svelte';
	import CoverageStatus from '#lib/components/map/CoverageStatus.svelte';
	import ZoomControls from '#lib/components/map/ZoomControls.svelte';
	import MapFrame, { type FcStyle } from '#lib/components/map/MapFrame.svelte';
	import { colorForIndex, lineWidthForLevel } from '#lib/utils/boundaryStyle.js';
	import { unionBbox, type Bbox } from '#lib/utils/bbox.js';
	import WelcomeModal from '#lib/components/map/WelcomeModal.svelte';
	import CustomBoundaryPanel from '#lib/components/map/CustomBoundaryPanel.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Alert from '#lib/components/ui/alert/index.js';
	import { ArrowRight, TriangleAlert } from '@lucide/svelte';
	import { customBoundary } from '#lib/stores/customBoundary.js';
	import { auth } from '#lib/stores/auth.js';
	import { welcomeEligible, dismissWelcome } from '#lib/welcome.js';
	import { features } from '#lib/stores/features.js';
	import { bbox as turfBbox } from '@turf/bbox';

	// ── Working selection ────────────────────────────────────────────────────────
	// The map page edits a local selection: the boundary chips plus, when exactly
	// one boundary is chosen, any features clicked on the map. Coverage is checked
	// live as it changes. Nothing is written to the store until "Find Data".

	function fcRefToBoundary(fc: FCRef): BoundaryResult {
		return {
			id: fc.id,
			name: fc.name,
			title: fc.title,
			short_name: fc.short_name,
			description: null,
			bbox: fc.bbox ?? null,
			group_name: null,
			group_title: null,
			group_class: null,
			group_level: null,
			source_name: null,
			source_url: null,
			license: null,
			license_url: null,
			citation: null,
			tags: [],
			date_added: null
		};
	}

	function boundaryToFcRef(b: BoundaryResult): FCRef {
		return { id: b.id, name: b.name, title: b.title, short_name: b.short_name, bbox: b.bbox ?? null };
	}

	/** Identifies a selection: FC ids, plus feature ids for a single-FC selection. */
	function selectionKeyOf(fcIds: number[], featureIds: number[]): string {
		return `${fcIds.join(',')}|${fcIds.length === 1 ? featureIds.join(',') : ''}`;
	}

	// ── Initialise the working selection from the committed store on mount ──────
	function initFromStore(): { boundaries: BoundaryResult[]; featureIds: number[]; bbox: Bbox | null } {
		const sel = get(selection);
		if (!sel) return { boundaries: [], featureIds: [], bbox: null };
		if (sel.mode === 'single') {
			return {
				boundaries: [fcRefToBoundary(sel.fc)],
				featureIds: [...sel.featureIds],
				bbox: sel.fc.bbox ?? null
			};
		}
		return {
			boundaries: sel.fcs.map(fcRefToBoundary),
			featureIds: [],
			bbox: unionBbox(sel.fcs.map((fc) => fc.bbox))
		};
	}

	// Don't restore a standard boundary if custom mode is active — the two are mutually exclusive
	const _init = get(customBoundary).active
		? { boundaries: [], featureIds: [], bbox: null }
		: initFromStore();

	onMount(() => {
		currentStep.set('map');
	});

	let allBoundaries = $state<BoundaryResult[]>([]);
	let boundaryPresets = $state<BoundaryPreset[]>([]);
	let boundaryLoading = $state(true);
	let boundaryLoadError = $state<string | null>(null);

	// Active tab in the selection panel. 'custom' mirrors customBoundary.active.
	type SelectionTab = 'explore' | 'browse' | 'custom';
	let activeTab = $state<SelectionTab>($customBoundary.active ? 'custom' : 'explore');

	// Browse All and Custom are beta features. Without either, the tab bar is
	// hidden and only the Explore search remains.
	let canBrowse = $derived($features.has('browse_boundaries'));
	let canCustom = $derived($features.has('custom_boundaries'));

	// Drop back to Explore once features resolve without access to the current
	// tab (e.g. a custom boundary left active from before signing out).
	$effect(() => {
		if (!$features.ready) return;
		if ((activeTab === 'browse' && !canBrowse) || (activeTab === 'custom' && !canCustom)) {
			switchTab('explore');
		}
	});

	function switchTab(tab: SelectionTab) {
		if (tab === 'custom') {
			// Activate custom mode; clear the standard selection
			customBoundary.activate();
			selection.clear();
			browseBoundaries = [];
			pendingFeatureIds = [];
		} else {
			// Leaving custom mode
			customBoundary.deactivate();
		}
		activeTab = tab;
	}

	// The Explore tab's search box text, so Restart can clear it too.
	let boundarySearch = $state('');

	/** Reset all boundary selection state and the map, and return to the Explore tab. */
	function resetAll() {
		boundarySearch = '';
		browseBoundaries = [];
		pendingFeatureIds = [];
		currentBbox = null;
		findDataError = null;
		selection.clear();
		customBoundary.reset();
		activeTab = 'explore';
		mapFrame?.resetView();
	}

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

	// Shown in a browser's first session only (see lib/welcome.ts), and never to
	// signed-in users, so it waits for the auth check rather than flashing open.
	const welcomeAllowed = browser && welcomeEligible();
	let welcomeClosed = $state(false);
	const showWelcome = $derived(welcomeAllowed && !welcomeClosed && $auth.status === 'anonymous');
	function closeWelcome() {
		welcomeClosed = true;
		dismissWelcome();
	}

	// When the welcome modal opens, the selection panel moves to the center where
	// the modal is, so closing the modal leaves the next step in the same place.
	// The first boundary selection docks it top left for the rest of the visit.
	// Starts docked: the server render cannot know about the modal.
	let panelDocked = $state(true);
	$effect(() => {
		if (showWelcome && browseBoundaries.length === 0 && !$customBoundary.active) panelDocked = false;
	});

	function dockPanel() {
		const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		if (!document.startViewTransition || reduceMotion) {
			panelDocked = true;
			return;
		}
		document.startViewTransition(async () => {
			panelDocked = true;
			await tick();
		});
	}

	let mapFrame: MapFrame;
	let mapZoom = $state(2);

	// Selected boundaries (shared between GeographySearch and BrowsePanel)
	let browseBoundaries = $state<BoundaryResult[]>(_init.boundaries);

	// Featured boundaries: tagged "featured", sorted by most recent, top 3.
	// Only a starting point, so hidden once anything is selected.
	let featuredBoundaries = $derived(
		browseBoundaries.length > 0
			? []
			: allBoundaries
					.filter((b) => b.tags?.includes('featured'))
					.sort((a, b) => {
						const dateA = a.date_added ? new Date(a.date_added).getTime() : 0;
						const dateB = b.date_added ? new Date(b.date_added).getTime() : 0;
						return dateB - dateA;
					})
					.slice(0, 3)
	);

	// Features clicked on the map; only meaningful when exactly one boundary is selected
	let pendingFeatureIds = $state<number[]>(_init.featureIds);
	let currentBbox = $state<Bbox | null>(_init.bbox);

	$effect(() => {
		if (!panelDocked && (browseBoundaries.length > 0 || $customBoundary.active)) dockPanel();
	});

	let userBbox = $derived.by(() => {
		if (!$customBoundary.active) return null;
		const fc = $customBoundary.finalFeatures;
		if (!fc || fc.features.length === 0) return null;
		try { return turfBbox(fc) as Bbox; } catch { return null; }
	});

	// Async state
	let findingData = $state(false);
	let findDataError = $state<string | null>(null);

	let selectionKey = $derived(
		selectionKeyOf(browseBoundaries.map((b) => b.id), pendingFeatureIds)
	);

	// Key of the selection last committed to the store, to warn when the working
	// selection no longer matches the one the cart was built from.
	let committedKey = $derived.by(() => {
		const sel = $selection;
		if (!sel) return null;
		if (sel.mode === 'single') return selectionKeyOf([sel.fc.id], sel.featureIds);
		return selectionKeyOf(sel.fcs.map((fc) => fc.id), []);
	});
	let selectionChanged = $derived(browseBoundaries.length > 0 && selectionKey !== committedKey);

	// Running dataset count for the current working selection
	let datasetCount = $state<number | null>(null);
	let datasetCountLoading = $state(false);
	let datasetCountError = $state(false);
	// Flat Feature.id list resolved by the coverage check, reused on "Find Data"
	let resolvedIds: { key: string; ids: number[] } | null = null;

	$effect(() => {
		const key = selectionKey;
		const fcIds = browseBoundaries.map((b) => b.id);
		const featureIds = fcIds.length === 1 ? [...pendingFeatureIds] : [];
		datasetCountError = false;
		if (fcIds.length === 0) { datasetCount = null; datasetCountLoading = false; return; }

		datasetCountLoading = true;
		let cancelled = false;

		const timer = setTimeout(async () => {
			try {
				const ids = featureIds.length > 0 ? featureIds : await fetchFeatureIds(fcIds);
				if (cancelled) return;
				resolvedIds = { key, ids };
				const datasets = await fetchDatasetsForFeatures(ids);
				if (!cancelled) { datasetCount = datasets.length; datasetCountLoading = false; }
			} catch {
				if (!cancelled) { datasetCount = null; datasetCountError = true; datasetCountLoading = false; }
			}
		}, 400);

		return () => { cancelled = true; clearTimeout(timer); };
	});

	// Nothing to find once coverage has confirmed there are no datasets
	let findDataDisabled = $derived(
		findingData || (!datasetCountLoading && datasetCount === 0)
	);

	// ── Derived map display values ───────────────────────────────────────────────

	// Full boundary metadata by name. Boundaries restored from the store carry
	// no group_level, so styles look it up here.
	let boundariesByName = $derived(new Map(allBoundaries.map((b) => [b.name, b])));

	// Per-FC display styles: distinct color cycled by index (matching the chip
	// swatches), line width by ADM level. Falls back gracefully for boundaries
	// without a group_level.
	let mapFcStyles = $derived.by<FcStyle[]>(() => {
		return browseBoundaries.map((b, idx) => {
			const meta = boundariesByName.get(b.name);
			return {
				id: b.id,
				name: b.name,
				bbox: meta?.bbox ?? b.bbox ?? null,
				color: colorForIndex(idx),
				lineWidth: lineWidthForLevel(meta?.group_level),
				title: meta?.title ?? b.title
			};
		});
	});

	// Feature clicking is available whenever exactly one boundary is selected.
	let activeFcName = $derived(browseBoundaries.length === 1 ? browseBoundaries[0].name : null);
	let displaySelectedFeatureIds = $derived(activeFcName ? pendingFeatureIds : []);

	// ── Handlers ─────────────────────────────────────────────────────────────────

	function handleBrowsePanelSelection(selectedIds: Set<number>) {
		// Convert selected IDs from BrowsePanel back to BoundaryResult array
		handleSelect(allBoundaries.filter((b) => selectedIds.has(b.id)));
	}

	function handleSelect(boundaries: BoundaryResult[]) {
		// Feature selection only applies to a single boundary; keep it only while
		// that same boundary remains the sole selection.
		const keepFeatures =
			boundaries.length === 1 &&
			browseBoundaries.length === 1 &&
			boundaries[0].id === browseBoundaries[0].id;
		if (!keepFeatures) pendingFeatureIds = [];

		browseBoundaries = boundaries;
		findDataError = null;

		const bbox = unionBbox(boundaries.map((b) => b.bbox));
		if (bbox) currentBbox = bbox;
	}

	async function handleFindData() {
		if (browseBoundaries.length === 0 || findDataDisabled) return;
		findDataError = null;
		findingData = true;
		try {
			// Deactivate custom boundary mode when committing a standard boundary
			customBoundary.deactivate();

			const fcs = browseBoundaries.map(boundaryToFcRef);
			const featureIds = fcs.length === 1 ? [...pendingFeatureIds] : [];

			// Write the working selection to the store
			selection.clear();
			selection.setSingleFC(fcs[0]);
			if (fcs.length === 1) {
				for (const id of featureIds) selection.toggleFeature(id);
			} else {
				for (const fc of fcs.slice(1)) selection.addFC(fc);
			}

			// Resolve flat Feature.id list for coverage checks and request submission,
			// reusing the list from the live coverage check when it is current
			const ids =
				resolvedIds?.key === selectionKey
					? resolvedIds.ids
					: featureIds.length > 0
						? featureIds
						: await fetchFeatureIds(fcs.map((fc) => fc.id));
			selection.setResolvedFeatureIds(ids);

			if (fcs.length === 1) {
				goto('/customize?selection');
			} else {
				goto(`/customize?fc=${fcs.map((fc) => fc.id).join(',')}`);
			}
		} catch (err) {
			console.error('Failed to commit selection:', err);
			findDataError = 'Something went wrong. Please try again.';
		} finally {
			findingData = false;
		}
	}

	function handleFeatureClick(featureId: number) {
		if (!activeFcName) return;
		pendingFeatureIds = pendingFeatureIds.includes(featureId)
			? pendingFeatureIds.filter((id) => id !== featureId)
			: [...pendingFeatureIds, featureId];
	}

	function handleZoomIn() {
		mapFrame?.zoomIn();
	}

	function handleZoomOut() {
		mapFrame?.zoomOut();
	}
</script>

{#snippet coverageStatus()}
	<CoverageStatus loading={datasetCountLoading} count={datasetCount} error={datasetCountError} />
{/snippet}

<!-- Shown whenever more than one boundary set is selected, overlapping or not:
     results stack the sets, one row per area, rather than intersecting them. -->
{#snippet multiSetNote()}
	<div class="rounded-md border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
		<strong>Each boundary set is kept separate.</strong> Every area gets its own row in your
		results, labelled with its boundary set. Areas that overlap are included once in each set,
		not combined or intersected.
	</div>
{/snippet}

<WelcomeModal bind:open={() => showWelcome, (open) => { if (!open) closeWelcome(); }} />

<div class="relative flex h-[calc(100vh-8rem)] flex-col">
	<!-- Left panel: search + selection status -->
	<div
		class="absolute z-10 max-w-[calc(100vw-2rem)] space-y-2 flex flex-col [view-transition-name:boundary-panel] {panelDocked
			? 'left-4 top-4 bottom-4 w-96'
			: 'left-1/2 top-1/2 max-h-[calc(100%-2rem)] w-[36rem] -translate-x-1/2 -translate-y-1/2'}"
	>
		<!-- Tabbed selection card -->
		<div class="card-surface flex flex-col min-h-0">
			<div class="p-4 pb-2 shrink-0">
				<div class="flex items-start justify-between gap-2 {canBrowse || canCustom ? 'mb-3' : ''}">
					<h2 class="text-h4 text-primary">
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
				{#if canBrowse || canCustom}
					<div class="grid {canBrowse && canCustom ? 'grid-cols-3' : 'grid-cols-2'} gap-1 rounded-md bg-muted p-1">
						<button
							class="min-h-8 rounded-md px-2 py-1.5 font-ui text-xs font-bold transition-colors {activeTab === 'explore' ? 'bg-card text-foreground shadow-card' : 'text-muted-foreground hover:text-foreground'}"
							aria-pressed={activeTab === 'explore'}
							onclick={() => switchTab('explore')}
						>
							Explore
						</button>
						{#if canBrowse}
							<button
								class="min-h-8 rounded-md px-2 py-1.5 font-ui text-xs font-bold transition-colors {activeTab === 'browse' ? 'bg-card text-foreground shadow-card' : 'text-muted-foreground hover:text-foreground'}"
								aria-pressed={activeTab === 'browse'}
								onclick={() => switchTab('browse')}
							>
								Browse All
							</button>
						{/if}
						{#if canCustom}
							<button
								class="min-h-8 rounded-md px-2 py-1.5 font-ui text-xs font-bold transition-colors {activeTab === 'custom' ? 'bg-card text-foreground shadow-card' : 'text-muted-foreground hover:text-foreground'}"
								aria-pressed={activeTab === 'custom'}
								onclick={() => switchTab('custom')}
							>
								Custom
							</button>
						{/if}
					</div>
				{/if}
			</div>

			<!-- Tab content (scrolls if too tall; explore tab needs overflow-visible so its dropdown isn't clipped) -->
			<div class="px-4 pb-4 pt-2 min-h-0 flex-1 {activeTab === 'explore' ? 'overflow-visible' : 'overflow-y-auto'}">
				{#if activeTab === 'explore'}
					<GeographySearch
						bind:searchText={boundarySearch}
						featuredBoundaries={featuredBoundaries}
						selectedBoundaries={browseBoundaries}
						proceedLabel={findingData ? 'Loading…' : 'Find Data'}
						proceedDisabled={findDataDisabled}
						onSelect={handleSelect}
						onProceed={handleFindData}
						belowSelection={coverageStatus}
					/>

					<!-- Feature-selection hint once a single boundary is selected -->
					{#if browseBoundaries.length === 1}
						<div class="mt-3 rounded-md border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
							{#if pendingFeatureIds.length === 0}
								Click features on the map to narrow your selection, or press
								<strong>Find Data</strong> to use the entire collection.
							{:else}
								<strong>{pendingFeatureIds.length}</strong>
								{pendingFeatureIds.length === 1 ? 'feature' : 'features'} selected — click more to
								add, or click a selected feature to deselect it.
							{/if}
						</div>
					{:else if browseBoundaries.length > 1}
						<div class="mt-3">{@render multiSetNote()}</div>
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

					{#if browseBoundaries.length > 1}
						<div class="mt-4">{@render multiSetNote()}</div>
					{/if}
					{#if browseBoundaries.length > 0}
						<div class="mt-4 pt-3 border-t flex items-center justify-between gap-2">
							{@render coverageStatus()}
							<Button size="sm" disabled={findDataDisabled} onclick={handleFindData}>
								{findingData ? 'Loading…' : 'Find Data'}
								{#if !findingData}<ArrowRight />{/if}
							</Button>
						</div>
					{/if}
				{:else if activeTab === 'custom'}
					<CustomBoundaryPanel />
				{/if}

				{#if activeTab !== 'custom'}
					{#if findDataError}
						<p class="mt-2 text-xs text-destructive">{findDataError}</p>
					{/if}

					{#if selectionChanged && $cartCount > 0}
						<Alert.Root variant="warning" role="status" class="mt-3">
							<TriangleAlert />
							<Alert.Description>
								Your selection has changed. Actual dataset coverage may vary across selected features.
							</Alert.Description>
						</Alert.Root>
					{/if}
				{/if}
			</div>
		</div>
	</div>

	<!-- Zoom Controls -->
	<div class="absolute right-4 top-4 z-10 flex flex-col items-center gap-1">
		<ZoomControls onZoomIn={handleZoomIn} onZoomOut={handleZoomOut} />
		<div
			title="Zoom level"
			class="flex cursor-default flex-col items-center rounded-md bg-card/85 px-1.5 py-0.5 font-ui text-muted-foreground shadow-card"
		>
			<span class="text-xs font-bold tabular-nums leading-tight">{mapZoom.toFixed(1)}</span>
			<span class="text-[0.625rem] leading-tight" aria-hidden="true">zoom</span>
			<span class="sr-only">zoom level</span>
		</div>
	</div>

	<!-- Map -->
	<MapFrame
		bind:this={mapFrame}
		class="flex-1"
		onZoomChange={(z) => (mapZoom = z)}
		fcStyles={$customBoundary.active ? [] : mapFcStyles}
		activeFcName={$customBoundary.active ? null : activeFcName}
		selectedFeatureIds={$customBoundary.active ? [] : displaySelectedFeatureIds}
		bbox={userBbox ?? currentBbox}
		onFeatureClick={handleFeatureClick}
		userGeoJSON={$customBoundary.active ? $customBoundary.finalFeatures : null}
	/>
</div>
