<Seo />
<svelte:head>
	<!-- Static content only, so it can't contain a closing script tag -->
	{@html `<script type="application/ld+json">${JSON.stringify(APP_JSON_LD)}</script>`}
</svelte:head>

<script lang="ts">
	import Seo from '#lib/components/layout/Seo.svelte';
	import { APP_JSON_LD } from '#lib/seo.js';
	import { get } from 'svelte/store';
	import { onMount, tick, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { browser } from '$app/env';
	import { currentStep } from '#lib/stores/ui.js';
	import { selection, customizeHref, type FCRef } from '#lib/stores/selection.js';
	import { cartCount } from '#lib/stores/cart.js';
	import { searchBoundaries, intersectingBoundaryIds, fetchFeatureIds, fetchDatasetsForFeatures, fetchBoundaryPresets, type BoundaryResult, type BoundaryPreset } from '#lib/api.js';
	import GeographySearch from '#lib/components/map/GeographySearch.svelte';
	import AreaSelectPanel from '#lib/components/map/AreaSelectPanel.svelte';
	import BoundaryBrowsePanel from '#lib/components/map/BoundaryBrowsePanel.svelte';
	import CoverageStatus from '#lib/components/map/CoverageStatus.svelte';
	import ZoomControls from '#lib/components/map/ZoomControls.svelte';
	import MapToolButton from '#lib/components/map/MapToolButton.svelte';
	import MapFrame, { type FcStyle } from '#lib/components/map/MapFrame.svelte';
	import type { LegendItem } from '#lib/components/map/SelectionLegend.svelte';
	import { assignColorSlots, colorForIndex, lineWidthForLevel } from '#lib/utils/boundaryStyle.js';
	import { unionBbox, type Bbox } from '#lib/utils/bbox.js';
	import { resolvePreset } from '#lib/utils/presets.js';
	import WelcomeModal from '#lib/components/map/WelcomeModal.svelte';
	import RequestPanel from '#lib/components/layout/RequestPanel.svelte';
	import CustomBoundaryPanel from '#lib/components/map/CustomBoundaryPanel.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Alert from '#lib/components/ui/alert/index.js';
	import { ArrowRight, ChevronDown, Map as MapIcon, TriangleAlert, Upload, SquareDashedMousePointer } from '@lucide/svelte';
	import DetailBack from '#lib/components/layout/DetailBack.svelte';
	import { openDetail } from '#lib/stepDetail.js';
	import { customBoundary } from '#lib/stores/customBoundary.js';
	import { auth } from '#lib/stores/auth.js';
	import { welcomeEligible, dismissWelcome } from '#lib/welcome.js';
	import { features } from '#lib/stores/features.js';
	import { bbox as turfBbox } from '@turf/bbox';

	// ── Working selection ────────────────────────────────────────────────────────
	// The map page edits a local selection: the boundary sets plus, when exactly
	// one boundary is chosen, any features clicked on the map. Every change is
	// saved to the selection store straight away, so the request (and the
	// Customize and Review steps) always follow what is selected here. Coverage
	// is checked live as it changes. "Find Data" only moves on to Customize.

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
	type SelectionTab = 'explore' | 'custom';
	let activeTab = $state<SelectionTab>($customBoundary.active ? 'custom' : 'explore');

	// The bulk select list
	let bulkOpen = $state(false);
	// Custom upload is a beta feature; without it only the search is shown.
	let canCustom = $derived($features.has('custom_boundaries'));

	// Drop back to Explore once features resolve without access to the current
	// tab (e.g. a custom boundary left active from before signing out).
	$effect(() => {
		if (!$features.ready) return;
		if (activeTab === 'custom' && !canCustom) {
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

	let userBbox = $derived.by(() => {
		if (!$customBoundary.active) return null;
		const fc = $customBoundary.finalFeatures;
		if (!fc || fc.features.length === 0) return null;
		try { return turfBbox(fc) as Bbox; } catch { return null; }
	});


	let selectionKey = $derived(
		selectionKeyOf(browseBoundaries.map((b) => b.id), pendingFeatureIds)
	);

	// Save every change to the store. Skipped while it already matches (as on
	// arrival), so a resolved feature list already in the store is kept.
	function storeKey(): string | null {
		const sel = get(selection);
		if (!sel) return null;
		if (sel.mode === 'single') return selectionKeyOf([sel.fc.id], sel.featureIds);
		return selectionKeyOf(sel.fcs.map((fc) => fc.id), []);
	}
	$effect(() => {
		if ($customBoundary.active) return;
		const key = selectionKey;
		const fcs = browseBoundaries.map(boundaryToFcRef);
		const featureIds = fcs.length === 1 ? [...pendingFeatureIds] : [];
		if (fcs.length === 0 ? get(selection) === null : key === untrack(storeKey)) return;
		untrack(() => selection.replace(fcs, featureIds));
	});

	// Warn when datasets were chosen for a different selection than the one
	// now on the map: the selection as the page opened, compared with now.
	const arrivalKey = selectionKeyOf(_init.boundaries.map((b) => b.id), _init.featureIds);
	let selectionChanged = $derived(
		_init.boundaries.length > 0 && browseBoundaries.length > 0 && selectionKey !== arrivalKey
	);

	// Running dataset count for the current working selection
	let datasetCount = $state<number | null>(null);
	let datasetCountLoading = $state(false);
	let datasetCountError = $state(false);

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
				// The request needs the flat list; save it while it still matches.
				if (key === storeKey()) selection.setResolvedFeatureIds(ids);
				const datasets = await fetchDatasetsForFeatures(ids);
				if (!cancelled) { datasetCount = datasets.length; datasetCountLoading = false; }
			} catch {
				if (!cancelled) { datasetCount = null; datasetCountError = true; datasetCountLoading = false; }
			}
		}, 400);

		return () => { cancelled = true; clearTimeout(timer); };
	});

	// Nothing to find once coverage has confirmed there are no datasets
	let findDataDisabled = $derived(!datasetCountLoading && datasetCount === 0);

	// ── Derived map display values ───────────────────────────────────────────────

	// Presets offered in the Explore search, each with the boundary sets it adds
	let presetOptions = $derived(
		boundaryPresets.map((preset) => ({ preset, members: resolvePreset(preset, allBoundaries) }))
	);

	// Full boundary metadata by name. Boundaries restored from the store carry
	// no group_level, so styles look it up here.
	let boundariesByName = $derived(new Map(allBoundaries.map((b) => [b.name, b])));

	// Each set keeps its color while it stays selected, so removing one doesn't
	// recolor the rest. Remembered across changes here rather than in state:
	// whichever way the selection changes (search, Browse, Clear All), the
	// slots follow it.
	let colorSlotMemo = new Map<number, number>();
	let colorSlots = $derived.by(() => {
		colorSlotMemo = assignColorSlots(colorSlotMemo, browseBoundaries.map((b) => b.id));
		return colorSlotMemo;
	});

	// Per-FC display styles: a color slot per set (matching the legend glyphs),
	// line width by ADM level. Falls back gracefully for boundaries without a
	// group_level.
	let mapFcStyles = $derived.by<FcStyle[]>(() => {
		return browseBoundaries.map((b) => {
			const meta = boundariesByName.get(b.name);
			return {
				id: b.id,
				name: b.name,
				bbox: meta?.bbox ?? b.bbox ?? null,
				color: colorForIndex(colorSlots.get(b.id) ?? 0),
				lineWidth: lineWidthForLevel(meta?.group_level),
				title: meta?.title ?? b.title
			};
		});
	});

	// The selection list, drawn as a key to the map
	let legendItems = $derived<LegendItem[]>(
		browseBoundaries.map((b, idx) => {
			const meta = boundariesByName.get(b.name);
			const style = mapFcStyles[idx];
			return {
				id: b.id,
				title: meta?.title ?? b.title ?? b.name,
				color: style.color,
				lineWidth: style.lineWidth,
				level: meta?.group_level ?? null,
				source: meta?.source_name ?? null,
				group: meta?.group_title ?? null
			};
		})
	);

	// The set hovered or focused in the selection list, highlighted on the map
	let highlightedFcId = $state<number | null>(null);

	/** Zoom the map to one selected set; on a narrow screen, show the map too. */
	function zoomToBoundary(id: number) {
		const bbox = mapFcStyles.find((s) => s.id === id)?.bbox;
		if (!bbox) return;
		openDetail();
		mapFrame?.fitBbox(bbox);
	}

	// Feature clicking is available whenever exactly one boundary is selected.
	let activeFcName = $derived(browseBoundaries.length === 1 ? browseBoundaries[0].name : null);
	let displaySelectedFeatureIds = $derived(activeFcName ? pendingFeatureIds : []);

	// ── Handlers ─────────────────────────────────────────────────────────────────

	function handleBrowsePanelSelection(selectedIds: Set<number>) {
		// Convert selected IDs from BrowsePanel back to BoundaryResult array
		handleSelect(allBoundaries.filter((b) => selectedIds.has(b.id)));
	}

	function handleSelect(boundaries: BoundaryResult[]) {
		if (activeTab === 'custom' && boundaries.length > 0) switchTab('explore');
		// Feature selection only applies to a single boundary; keep it only while
		// that same boundary remains the sole selection.
		const keepFeatures =
			boundaries.length === 1 &&
			browseBoundaries.length === 1 &&
			boundaries[0].id === browseBoundaries[0].id;
		if (!keepFeatures) pendingFeatureIds = [];

		browseBoundaries = boundaries;

		const bbox = unionBbox(boundaries.map((b) => b.bbox));
		if (bbox) currentBbox = bbox;
	}

	// Area of interest tool: drag a box on the map, then pick ADM levels to add
	// every boundary set at those levels whose extent intersects it.
	let aoiState = $state<'idle' | 'drawing' | 'choosing'>('idle');
	// null while the lookup runs
	let aoiMatches = $state<BoundaryResult[] | null>(null);
	let aoiError = $state(false);

	function toggleAreaSelect() {
		if (aoiState !== 'idle') return endAreaSelect();
		aoiState = 'drawing';
		mapFrame?.startAreaSelect((bbox) => {
			if (!bbox) {
				aoiState = 'idle';
				return;
			}
			aoiMatches = null;
			aoiError = false;
			aoiState = 'choosing';
			intersectingBoundaryIds(bbox)
				.then((ids) => {
					const hit = new Set(ids);
					aoiMatches = allBoundaries.filter((b) => hit.has(b.id));
				})
				.catch(() => {
					aoiError = true;
					aoiMatches = [];
				});
		});
	}

	function endAreaSelect() {
		aoiState = 'idle';
		aoiMatches = null;
		aoiError = false;
		mapFrame?.clearAreaSelect();
	}

	/** Add to the selection, the same as picking each from the search. */
	function addAreaBoundaries(boundaries: BoundaryResult[]) {
		const have = new Set(browseBoundaries.map((b) => b.id));
		handleSelect([...browseBoundaries, ...boundaries.filter((b) => !have.has(b.id))]);
		endAreaSelect();
	}

	/** Move on to Customize; the selection itself is already saved. */
	function handleFindData() {
		if (browseBoundaries.length === 0 || findDataDisabled) return;
		const href = get(customizeHref);
		if (href) goto(href);
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

	// The extent of what's selected: an uploaded boundary, or every selected set
	let selectionBbox = $derived(userBbox ?? unionBbox(mapFcStyles.map((s) => s.bbox)));

	function handleZoomToSelection() {
		if (selectionBbox) mapFrame?.fitBbox(selectionBbox);
	}
</script>

{#snippet coverageStatus()}
	<CoverageStatus loading={datasetCountLoading} count={datasetCount} error={datasetCountError} />
{/snippet}

<!-- Shown whenever more than one boundary set is selected, overlapping or not:
     results stack the sets, one row per feature, rather than intersecting them. -->
{#snippet multiSetNote()}
	<div class="rounded-md border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
		<strong>Each boundary set is kept separate.</strong> Every feature gets its own row in your
		results, labelled with its boundary set. Features that overlap are included once in each set,
		not combined or intersected.
		<a
			href="https://docs.geoquery.org/using-geoquery/multiple-boundaries/"
			target="_blank"
			rel="noopener noreferrer"
			class="text-link hover:text-link-hover hover:underline"
			>Learn more<span class="sr-only"> about multiple boundary sets (opens in a new tab)</span></a
		>
	</div>
{/snippet}

<!-- Right under the Explore tab's search box. -->
{#snippet exploreSearchNote()}
	<!-- Bulk select: every boundary set grouped by ADM level, to tick whole levels at once.
	     Open to everyone, signed in or not. Pulled up toward the search box, with a little room below. -->
	<div class="-mt-2">
			<Button
				variant="ghost"
				size="sm"
				class="-ml-2 h-6 gap-1 px-2 text-xs text-muted-foreground hover:text-foreground"
				aria-expanded={bulkOpen}
				aria-controls="bulk-select"
				onclick={() => (bulkOpen = !bulkOpen)}
			>
				Bulk select
				<ChevronDown class="transition-transform {bulkOpen ? 'rotate-180' : ''}" />
			</Button>
			{#if bulkOpen}
				<div id="bulk-select" class="mt-2 rounded-md border p-3">
					{#if boundaryLoadError}
						<p class="text-sm text-destructive">{boundaryLoadError}</p>
					{:else}
						<BoundaryBrowsePanel
							allBoundaries={allBoundaries}
							selectedIds={new Set(browseBoundaries.map((b) => b.id))}
							onSelectionChange={handleBrowsePanelSelection}
							loading={boundaryLoading}
						/>
					{/if}
				</div>
			{/if}
	</div>
	{#if browseBoundaries.length > 1}
		{@render multiSetNote()}
	{/if}
{/snippet}

<!-- Under the Explore tab's selection list, above Find Data: coverage, then
     how to narrow a single boundary set. -->
{#snippet exploreSelectionNotes()}
	{@render coverageStatus()}
	{#if browseBoundaries.length === 1}
		<!-- Feature-selection hint once a single boundary is selected -->
		<div class="rounded-md border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
			{#if pendingFeatureIds.length === 0}
				Click features on the map to narrow your selection, or leave them all
				unselected to use the entire boundary set.
				<button type="button" class="font-bold text-link hover:text-link-hover hover:underline md:hidden" onclick={openDetail}>
					Open map
				</button>
			{:else}
				<strong>{pendingFeatureIds.length}</strong>
				{pendingFeatureIds.length === 1 ? 'feature' : 'features'} selected — click more to
				add, or click a selected feature to deselect it.
				<button type="button" class="font-bold text-link hover:text-link-hover hover:underline md:hidden" onclick={openDetail}>
					Open map
				</button>
			{/if}
		</div>
	{/if}
{/snippet}

<WelcomeModal bind:open={() => showWelcome, (open) => { if (!open) closeWelcome(); }} />

<div class="flex h-[calc(100dvh-var(--header-height,8rem))]">
	<RequestPanel active="map">
		{#snippet actions()}
			<!-- Narrow screens: the map is a view of its own (lib/stepDetail.ts) -->
			<Button size="sm" variant="outline" class="-my-1 md:hidden" onclick={openDetail}>
				<MapIcon />
				Show map
			</Button>
		{/snippet}
		<div>
				<!-- Above the boundary search, so it's seen before changing anything else -->
				{#if activeTab !== 'custom' && selectionChanged && $cartCount > 0}
					<Alert.Root variant="warning" role="status" class="mb-3">
						<TriangleAlert />
						<Alert.Description>
							Your selection has changed. Actual dataset coverage may vary across selected features.
						</Alert.Description>
					</Alert.Root>
				{/if}

				<GeographySearch
						bind:searchText={boundarySearch}
						presets={presetOptions}
						featuredBoundaries={featuredBoundaries}
						selectedBoundaries={browseBoundaries}
						proceedLabel="Find Data"
						proceedDisabled={findDataDisabled}
						onSelect={handleSelect}
						onProceed={handleFindData}
						onClear={resetAll}
						belowSearch={exploreSearchNote}
						belowSelection={exploreSelectionNotes}
						{legendItems}
						onZoom={zoomToBoundary}
						onHighlight={(id) => (highlightedFcId = id)}
						hideActions={activeTab === 'custom'}
					/>
				{#if canCustom}
					<!-- Custom upload: a beta feature, opened below the search. It
					     replaces any standard selection while open. -->
					<div class="mt-3 border-t pt-3">
						<Button
							variant="ghost"
							size="sm"
							class="-ml-2 h-7 gap-1.5 px-2 text-xs text-muted-foreground hover:text-foreground"
							aria-expanded={activeTab === 'custom'}
							aria-controls="custom-upload"
							onclick={() => switchTab(activeTab === 'custom' ? 'explore' : 'custom')}
						>
							<Upload />
							{activeTab === 'custom' ? 'Cancel custom upload' : 'Custom upload'}
						</Button>
						{#if activeTab === 'custom'}
							<div id="custom-upload" class="mt-2">
								<CustomBoundaryPanel />
							</div>
						{/if}
					</div>
				{/if}
		</div>
	</RequestPanel>

	<!-- Map, beside the panel -->
	<div class="step-main relative flex min-w-0 flex-1 flex-col">
	<DetailBack label="Boundaries" class="absolute left-4 top-4 z-10 shadow-card" />
	<!-- Zoom Controls -->
	<div class="absolute right-4 top-4 z-10 flex flex-col items-center gap-1">
		<ZoomControls
			onZoomIn={handleZoomIn}
			onZoomOut={handleZoomOut}
			onZoomToSelection={handleZoomToSelection}
			selectionEmpty={!selectionBbox}
		/>
		<div class="card-surface">
			<MapToolButton
				pressed={aoiState !== 'idle'}
				label={aoiState === 'idle' ? 'Select boundaries by area' : 'Cancel area selection'}
				tooltip={aoiState === 'idle' ? 'Select boundaries by area: drag a box on the map' : undefined}
				onclick={toggleAreaSelect}
			>
				<SquareDashedMousePointer />
			</MapToolButton>
		</div>
		<!-- Zoom level readout: hidden for now -->
		<div
			hidden
			title="Zoom level"
			class="flex cursor-default flex-col items-center rounded-md bg-card/85 px-1.5 py-0.5 font-ui text-muted-foreground shadow-card"
		>
			<span class="text-xs font-bold tabular-nums leading-tight">{mapZoom.toFixed(1)}</span>
			<span class="text-[0.625rem] leading-tight" aria-hidden="true">zoom</span>
			<span class="sr-only">zoom level</span>
		</div>
	</div>

	<!-- Area of interest: a hint while drawing, then the levels to add -->
	{#if aoiState === 'drawing'}
		<div class="card-surface absolute right-[4.5rem] top-4 z-10 px-3 py-2 text-xs" role="status">
			Drag on the map to draw an area. <span class="text-muted-foreground">Esc to cancel.</span>
		</div>
	{:else if aoiState === 'choosing'}
		<div class="absolute right-[4.5rem] top-4 z-10">
			<AreaSelectPanel
				matches={aoiMatches}
				error={aoiError}
				selectedIds={new Set(browseBoundaries.map((b) => b.id))}
				onAdd={addAreaBoundaries}
				onCancel={endAreaSelect}
			/>
		</div>
	{/if}

	<!-- Map -->
	<MapFrame
		bind:this={mapFrame}
		class="flex-1"
		onZoomChange={(z) => (mapZoom = z)}
		fcStyles={$customBoundary.active ? [] : mapFcStyles}
		activeFcName={$customBoundary.active ? null : activeFcName}
		selectedFeatureIds={$customBoundary.active ? [] : displaySelectedFeatureIds}
		highlightFcId={$customBoundary.active ? null : highlightedFcId}
		bbox={userBbox ?? currentBbox}
		onFeatureClick={handleFeatureClick}
		userGeoJSON={$customBoundary.active ? $customBoundary.finalFeatures : null}
	/>
	</div>
</div>
