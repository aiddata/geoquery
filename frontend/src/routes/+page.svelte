<script lang="ts">
	import { get } from 'svelte/store';
	import { goto } from '$app/navigation';
	import { browser } from '$app/environment';
	import { currentStep } from '$lib/stores/ui';
	import { selection, type FCRef } from '$lib/stores/selection';
	import { cartCount } from '$lib/stores/cart';
	import { searchBoundaries, fetchFeatureIds, fetchDatasetsForFeatures, type BoundaryResult } from '$lib/api';
	import GeographySearch from '$lib/components/map/GeographySearch.svelte';
	import ZoomControls from '$lib/components/map/ZoomControls.svelte';
	import MapFrame from '$lib/components/map/MapFrame.svelte';
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

	const _init = initFromStore();

	$effect(() => {
		currentStep.set('map');
	});

	let featuredBoundaries = $state<BoundaryResult[]>([]);
	$effect(() => {
		searchBoundaries('', 5).then((results) => {
			featuredBoundaries = results;
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

	// Search preview state
	let pendingBoundary = $state<BoundaryResult | null>(null);
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
		if (pendingBoundary && !names.includes(pendingBoundary.name))
			names.push(pendingBoundary.name);
		return names;
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

	function handleSelect(boundary: BoundaryResult | null) {
		if (!boundary || boundary.name !== pendingBoundary?.name) pendingFeatureIds = [];
		pendingBoundary = boundary;
		if (boundary?.bbox) currentBbox = boundary.bbox;
	}

	function handleProceed(boundary: BoundaryResult) {
		const fc: FCRef = { id: boundary.id, name: boundary.name, title: boundary.title, bbox: boundary.bbox ?? null };
		if (addingAnother) {
			if (!staged) {
				staged = { mode: 'multi', fcs: [fc] };
			} else if (staged.mode === 'single') {
				if (staged.fc.id !== fc.id) staged = { mode: 'multi', fcs: [staged.fc, fc] };
			} else if (!staged.fcs.some((f) => f.id === fc.id)) {
				staged = { ...staged, fcs: [...staged.fcs, fc] };
			}
			addingAnother = false;
		} else {
			staged = { mode: 'single', fc, featureIds: [...pendingFeatureIds] };
			if (boundary.bbox) currentBbox = boundary.bbox;
		}
		selectionModified = true;
		stagedNeedsConfirm = false;
		pendingFeatureIds = [];
		pendingBoundary = null;
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
	<div class="absolute left-4 top-4 z-10 w-96 max-w-[calc(100vw-2rem)] space-y-2">
		{#if staged}
			<!-- Staged selection summary -->
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
						onclick={() => { staged = null; selectionModified = false; stagedNeedsConfirm = false; addingAnother = false; pendingBoundary = null; pendingFeatureIds = []; }}
						class="shrink-0 text-muted-foreground hover:text-destructive"
					>
						Reset
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
					{#if !addingAnother && !hasIndividualFeatures && !stagedNeedsConfirm}
						<Button
							size="sm"
							variant="outline"
							onclick={() => { addingAnother = true; pendingBoundary = null; }}
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
		{/if}

		{#if !staged || addingAnother}
			{#if $customBoundary.active && !addingAnother}
				<!-- Custom boundary upload panel -->
				<CustomBoundaryPanel />
			{:else}
				<!-- Search panel (initial selection or adding another) -->
				{#key addingAnother}
					<GeographySearch
						featuredBoundaries={addingAnother ? [] : featuredBoundaries}
						proceedLabel={pendingFeatureIds.length > 0 ? 'Save Selected' : 'Save All'}
						proceedTooltip={pendingFeatureIds.length > 0
							? 'Individual feature selections are limited to one boundary collection.'
							: 'Save this boundary. You can then add another boundary to combine multiple collections.'}
						onSelect={handleSelect}
						onProceed={handleProceed}
					/>
				{/key}

				<!-- Feature-selection hint once a boundary is previewed -->
				{#if pendingBoundary && !addingAnother}
					<div class="rounded-md border bg-card px-3 py-2 text-xs text-muted-foreground shadow">
						{#if pendingFeatureIds.length === 0}
							Click features on the map to narrow your selection, then press
							<strong>Save Selected</strong>. Or press <strong>Save All</strong> now to use the
							entire collection.
						{:else}
							<strong>{pendingFeatureIds.length}</strong>
							{pendingFeatureIds.length === 1 ? 'feature' : 'features'} selected — click more to
							add, or click a selected feature to deselect it.
						{/if}
					</div>
				{/if}

				{#if addingAnother}
					<button
						class="px-1 text-sm text-muted-foreground underline hover:text-foreground"
						onclick={() => { addingAnother = false; pendingBoundary = null; }}
					>
						Cancel
					</button>
				{:else}
					<!-- Toggle to custom boundary mode -->
					<button
						class="w-full rounded-md border bg-card px-3 py-2.5 text-xs text-muted-foreground shadow hover:bg-muted/50 hover:text-foreground transition-colors text-center"
						onclick={() => customBoundary.activate()}
					>
						Use my own boundary file instead →
					</button>
				{/if}
			{/if}
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
		fcNames={mapFcNames}
		{activeFcName}
		selectedFeatureIds={displaySelectedFeatureIds}
		bbox={userBbox ?? currentBbox}
		onFeatureClick={handleFeatureClick}
		userGeoJSON={$customBoundary.active ? $customBoundary.finalFeatures : null}
	/>
</div>
