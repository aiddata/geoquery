<script lang="ts">
	import { onMount, onDestroy, tick } from 'svelte';
	import { get } from 'svelte/store';
	import { page } from '$app/state';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import * as Collapsible from '$lib/components/ui/collapsible';
	import * as Alert from '$lib/components/ui/alert';
	import * as Select from '$lib/components/ui/select';
	import { Button } from '$lib/components/ui/button';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Input } from '$lib/components/ui/input';
	import MapLegend from '$lib/components/viz/MapLegend.svelte';
	import { basemapStyle, followTheme } from '$lib/map/basemap';
	import { addChoroplethLayers, refreshChoroplethTheme, fcFillId, fcLineId, fcSourceId } from '$lib/map/choropleth';
	import { exportMapImage as drawMapExport } from '$lib/map/exportMapImage';
	import { resolvedTheme } from '$lib/stores/theme';
	import BoundaryBrowsePanel from '$lib/components/map/BoundaryBrowsePanel.svelte';
	import {
		searchBoundaries, fetchBoundaryPresets, fetchExploreAvailable, fetchExploreData,
		boundaryTileUrl,
		type BoundaryResult, type BoundaryPreset, type ExploreDataset, type VizPayload,
	} from '$lib/api';
	import { protomapsApiKey } from '$lib/map/protomapsKey';
	import {
		PALETTES, DEFAULT_PALETTE, NO_VALUE_COLOR, quantileBreaks, equalBreaks, buildColorExpression,
		fmt, prettyColumn, escapeHtml, computeStats,
	} from '$lib/viz';
	import { parseFormula, evaluateFormula, formulaColumns } from '$lib/formula';
	import { GripVertical, AlertCircle, Plus, X, Search, ChevronDown, Download, ChartColumn, Map as MapIcon } from '@lucide/svelte';

	let activeTab = $state<'map' | 'charts'>('map');
	// Charts load on the first visit to their tab, then stay mounted so configured cards survive tab switches
	let chartsVisited = $state(false);
	$effect(() => {
		if (activeTab === 'charts') chartsVisited = true;
	});
	const loadChartPanel = () => import('$lib/components/viz/ChartPanel.svelte');

	// ── Section open state ────────────────────────────────────────────────────
	let boundariesOpen = $state(true);
	let datasetsOpen = $state(true);
	let stylingOpen = $state(false);
	let infoOpen = $state(true);

	// ── All boundaries (for browse panel) ────────────────────────────────────
	let allBoundaries = $state<BoundaryResult[]>([]);
	let presets = $state<BoundaryPreset[]>([]);
	let browsePanelLoading = $state(true);

	// ── FC selection ──────────────────────────────────────────────────────────
	let selectedFCs = $state<BoundaryResult[]>([]);
	let fcQuery = $state('');
	let fcSuggestions = $state<BoundaryResult[]>([]);
	let fcSearchOpen = $state(false);
	let searchDebounce: ReturnType<typeof setTimeout> | null = null;

	let selectedIds = $derived(new Set(selectedFCs.map((f) => f.id)));

	async function onFcInput() {
		if (searchDebounce) clearTimeout(searchDebounce);
		searchDebounce = setTimeout(async () => {
			if (!fcQuery.trim()) { fcSuggestions = []; return; }
			try {
				fcSuggestions = (await searchBoundaries(fcQuery, 8)).filter(
					(r) => !selectedFCs.some((s) => s.id === r.id)
				);
			} catch { fcSuggestions = []; }
		}, 200);
	}

	async function handleSelectionChange(newIds: Set<number>) {
		layerError = '';
		const newFCs = [...newIds]
			.map((id) => allBoundaries.find((b) => b.id === id))
			.filter((b): b is BoundaryResult => !!b);

		const toRemove = selectedFCs.filter((fc) => !newIds.has(fc.id));
		const toAdd = newFCs.filter((fc) => !selectedFCs.some((s) => s.id === fc.id));

		for (const fc of toRemove) removeFCFromMap(fc.name);

		const failed: string[] = [];
		for (const fc of toAdd) {
			try {
				await addFCToMap(fc);
			} catch {
				failed.push(fc.title || fc.name);
			}
		}
		if (failed.length) layerError = `Failed to load layer(s): ${failed.join(', ')}`;

		selectedFCs = newFCs.filter((fc) => !failed.includes(fc.title || fc.name));

		if (selectedFCs.length === 0) {
			availableDatasets = [];
			data = null; checkedPoIds = new Set(); activeColumn = null;
			checkedColumns = new Set(); partialCols = new Set();
		} else {
			refitMap();
			await refreshAvailable();
			// Filter out PO IDs that no longer exist in the updated available options
			const validPoIds = new Set(
				availableDatasets.flatMap((ds) => ds.options.map((o) => o.po_id))
			);
			checkedPoIds = new Set([...checkedPoIds].filter((id) => validPoIds.has(id)));
			if (checkedPoIds.size > 0) void loadExploreData();
		}
	}

	// Also handle direct typeahead additions (search suggestions outside browse panel)
	async function addFCFromSearch(fc: BoundaryResult) {
		fcQuery = ''; fcSuggestions = []; fcSearchOpen = false;
		await handleSelectionChange(new Set([...selectedIds, fc.id]));
	}

	// ── Available options ─────────────────────────────────────────────────────
	let availableDatasets = $state<ExploreDataset[]>([]);
	let availableLoading = $state(false);

	async function refreshAvailable() {
		if (selectedFCs.length === 0) { availableDatasets = []; return; }
		availableLoading = true;
		try { availableDatasets = await fetchExploreAvailable(selectedFCs.map((f) => f.id)); }
		catch { availableDatasets = []; }
		finally { availableLoading = false; }
	}

	// ── PO selection → data fetch ─────────────────────────────────────────────
	let checkedPoIds = $state<Set<number>>(new Set());
	let data = $state<VizPayload | null>(null);
	let dataLoading = $state(false);
	let dataError = $state('');
	let layerError = $state('');
	let partialCols = $state<Set<string>>(new Set());

	async function togglePo(poId: number, checked: boolean) {
		const next = new Set(checkedPoIds);
		if (checked) next.add(poId); else next.delete(poId);
		checkedPoIds = next;
		if (next.size === 0 || selectedFCs.length === 0) {
			data = null; activeColumn = null; checkedColumns = new Set(); partialCols = new Set(); return;
		}
		await loadExploreData();
	}

	async function loadExploreData() {
		if (selectedFCs.length === 0 || checkedPoIds.size === 0) return;
		dataLoading = true; dataError = '';
		try {
			const result = await fetchExploreData(selectedFCs.map((f) => f.id), [...checkedPoIds]);
			data = result;
			const total = Object.keys(result.features).length;
			const partial = new Set<string>();
			for (const col of result.columns) {
				let nulls = 0;
				for (const feat of Object.values(result.features)) {
					if (feat[col] === null || feat[col] === undefined) nulls++;
				}
				if (nulls > 0 && nulls < total) partial.add(col);
			}
			partialCols = partial;
			if (!activeColumn || !result.columns.includes(activeColumn)) {
				activeColumn = result.columns[0] ?? null;
				checkedColumns = activeColumn ? new Set([activeColumn]) : new Set();
			}
			await tick();
			if (mapReady) void applyColors();
		} catch (e) {
			dataError = e instanceof Error ? e.message : 'Failed to load data.';
		} finally { dataLoading = false; }
	}

	// ── Map ───────────────────────────────────────────────────────────────────
	let mapContainer: HTMLDivElement;
	let map: maplibregl.Map | null = $state(null);
	let mapReady = $state(false);

	let checkedColumns = $state<Set<string>>(new Set());
	let activeColumn = $state<string | null>(null);
	let currentPalette = $state<string>(DEFAULT_PALETTE);
	let currentMethod = $state<'quantile' | 'equal' | 'jenks'>('quantile');
	let currentBreaks = $state<number[] | null>(null);
	let hiddenFCs = $state<Set<string>>(new Set());
	let fcOrder = $state<string[]>([]);
	let stats = $state<{ min: number; max: number; mean: number; n: number } | null>(null);
	let popup: maplibregl.Popup | null = null;
	let stopTheme: (() => void) | undefined;

	const METHOD_LABELS = {
		quantile: 'Quantile',
		equal: 'Equal interval',
		jenks: 'Natural Breaks (Jenks)'
	} as const;

	function setColumnChecked(key: string, checked: boolean) {
		const next = new Set(checkedColumns);
		if (checked) { next.add(key); activeColumn = key; }
		else { next.delete(key); if (activeColumn === key) activeColumn = [...next][0] ?? null; }
		checkedColumns = next;
	}

	// ── Custom indices ────────────────────────────────────────────────────────
	interface CustomIndex { name: string; formula: string; values: Record<string, number | null>; nullCount: number; }
	let customIndices = $state<CustomIndex[]>([]);
	let showIndexBuilder = $state(false);
	let indexName = $state(''); let indexFormula = $state(''); let indexError = $state('');

	function resolveValue(featureId: string, col: string): unknown {
		if (col.startsWith('~')) return customIndices.find((c) => `~${c.name}` === col)?.values[featureId] ?? null;
		return data?.features[featureId]?.[col] ?? null;
	}

	function addCustomIndex() {
		indexError = '';
		if (!indexName.trim()) { indexError = 'Name required.'; return; }
		if (customIndices.some((c) => c.name === indexName.trim())) { indexError = 'Name already used.'; return; }
		let expr;
		try { expr = parseFormula(indexFormula); } catch (e) { indexError = e instanceof Error ? e.message : 'Parse error'; return; }
		const allCols = new Set([...(data?.columns ?? []), ...customIndices.map((c) => c.name)]);
		const missing = formulaColumns(expr).filter((c) => !allCols.has(c));
		if (missing.length) { indexError = `Unknown columns: ${missing.join(', ')}`; return; }
		const values: Record<string, number | null> = {};
		let nullCount = 0;
		for (const [id, feat] of Object.entries(data?.features ?? {})) {
			const v = evaluateFormula(expr, feat as Record<string, unknown>);
			values[id] = v; if (v === null) nullCount++;
		}
		const name = indexName.trim();
		customIndices = [...customIndices, { name, formula: indexFormula, values, nullCount }];
		checkedColumns = new Set([...checkedColumns, `~${name}`]);
		activeColumn = `~${name}`;
		indexName = ''; indexFormula = ''; showIndexBuilder = false;
	}

	function removeCustomIndex(name: string) {
		customIndices = customIndices.filter((c) => c.name !== name);
		const key = `~${name}`; const next = new Set(checkedColumns); next.delete(key);
		checkedColumns = next;
		if (activeColumn === key) activeColumn = [...checkedColumns][0] ?? null;
	}

	// A whole selection carried in the URL: which boundaries, which processing
	// options, and how to style the result. The MCP server returns one of these
	// links with every map and table, so opening it must land on the same view
	// the assistant described — see backend/mcp_server/tools/explore.py:viz_url.
	function idsParam(name: string): number[] {
		return (page.url.searchParams.get(name) ?? '')
			.split(',')
			.map((v) => parseInt(v, 10))
			.filter((v) => Number.isFinite(v));
	}

	function applyStyleParams() {
		const params = page.url.searchParams;

		const formula = params.get('formula');
		if (formula) {
			// Named after the formula itself, matching the `~<formula>` column
			// the server generates, so `col=` can refer to it.
			indexName = formula;
			indexFormula = formula;
			addCustomIndex();
		}

		const col = params.get('col');
		if (col && ((data?.columns ?? []).includes(col) || col.startsWith('~'))) {
			checkedColumns = new Set([...checkedColumns, col]);
			activeColumn = col;
		}

		const palette = params.get('palette');
		if (palette && palette in PALETTES) currentPalette = palette;

		const scheme = params.get('scheme');
		if (scheme === 'quantile' || scheme === 'equal' || scheme === 'jenks') {
			currentMethod = scheme;
		}
	}

	async function applyUrlSelection() {
		const fcIds = idsParam('fc');
		if (fcIds.length === 0) return;

		await handleSelectionChange(new Set(fcIds));

		const poIds = idsParam('po');
		if (poIds.length) {
			// Only options that actually turned out to be available for these
			// boundaries; a stale link should degrade, not error.
			const valid = new Set(availableDatasets.flatMap((ds) => ds.options.map((o) => o.po_id)));
			checkedPoIds = new Set(poIds.filter((id) => valid.has(id)));
			if (checkedPoIds.size) await loadExploreData();
		}
		applyStyleParams();
	}

	// ── Map init ──────────────────────────────────────────────────────────────
	onMount(async () => {
		// Load all boundaries and presets in parallel, creating the map while they arrive
		const lists = Promise.allSettled([
			searchBoundaries('', 0),
			fetchBoundaryPresets(),
		]);

		const key = await protomapsApiKey();
		map = new maplibregl.Map({
			container: mapContainer,
			preserveDrawingBuffer: true,
			style: basemapStyle(get(resolvedTheme), key),
			center: [0, 20], zoom: 2
		});
		map.on('load', () => { mapReady = true; });
		stopTheme = followTheme(map, key, () => {
			if (map) refreshChoroplethTheme(map, fcOrder);
		});

		const [allB, p] = await lists;
		allBoundaries = allB.status === 'fulfilled' ? allB.value : [];
		presets = p.status === 'fulfilled' ? p.value : [];
		browsePanelLoading = false;

		// After the map exists: addFCToMap waits on `load`, and loadExploreData
		// paints as soon as the layers are there.
		await applyUrlSelection();
	});

	// The map container has no layout while it sits behind the inactive tab on
	// first paint, so MapLibre can size its canvas to 0. Resize once the map is
	// ready and whenever the map tab is reactivated to keep the canvas correct.
	$effect(() => {
		if (activeTab === 'map' && map && mapReady) {
			requestAnimationFrame(() => map?.resize());
		}
	});

	async function addFCToMap(fc: BoundaryResult) {
		if (!map) return;
		if (!mapReady) await new Promise<void>((r) => { map!.once('load', () => r()); });
		if (map.getSource(fcSourceId(fc.name))) return;

		addChoroplethLayers(map, fc.name, boundaryTileUrl(fc.name));

		const fcName = fc.name;
		let hoveredId: number | null = null;
		map.on('mousemove', `fc-fill-${fcName}`, (e) => {
			if (!e.features?.length) return;
			const fid = e.features[0].id as number;
			if (hoveredId !== null && hoveredId !== fid)
				map!.setFeatureState({ source: `fc-${fcName}`, sourceLayer: fcName, id: hoveredId }, { hover: false });
			hoveredId = fid;
			map!.setFeatureState({ source: `fc-${fcName}`, sourceLayer: fcName, id: fid }, { hover: true });
			if (data?.features[String(fid)]) {
				if (!popup) popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '300px' });
				popup.setLngLat(e.lngLat).setHTML(renderPopupHtml(data.features[String(fid)], String(fid))).addTo(map!);
			}
		});
		map.on('mouseleave', `fc-fill-${fcName}`, () => {
			if (hoveredId !== null) {
				map!.setFeatureState({ source: `fc-${fcName}`, sourceLayer: fcName, id: hoveredId }, { hover: false });
				hoveredId = null;
			}
			popup?.remove(); popup = null;
		});

		fcOrder = [...fcOrder, fc.name];
	}

	function removeFCFromMap(fcName: string) {
		if (!map) return;
		if (map.getLayer(fcFillId(fcName))) map.removeLayer(fcFillId(fcName));
		if (map.getLayer(fcLineId(fcName))) map.removeLayer(fcLineId(fcName));
		if (map.getSource(`fc-${fcName}`)) map.removeSource(`fc-${fcName}`);
		fcOrder = fcOrder.filter((n) => n !== fcName);
	}

	function refitMap() {
		if (!map || selectedFCs.length === 0) return;
		const bboxes = selectedFCs.filter((f) => f.bbox).map((f) => f.bbox!);
		if (!bboxes.length) return;
		const w = Math.min(...bboxes.map((b) => b[0])); const s = Math.min(...bboxes.map((b) => b[1]));
		const e = Math.max(...bboxes.map((b) => b[2])); const n = Math.max(...bboxes.map((b) => b[3]));
		map.fitBounds([[w, s], [e, n]], { padding: 40, maxZoom: 10 });
	}

	// ── Colors ────────────────────────────────────────────────────────────────
	async function applyColors() {
		if (!map || !mapReady) return;
		if (!data || !activeColumn) {
			for (const fc of fcOrder) {
				if (map.getLayer(fcFillId(fc))) map.setPaintProperty(fcFillId(fc), 'fill-color', NO_VALUE_COLOR);
			}
			return;
		}
		const overrides = activeColumn.startsWith('~')
			? customIndices.find((c) => `~${c.name}` === activeColumn)?.values : undefined;
		const values: number[] = [];
		for (const [id, feat] of Object.entries(data.features)) {
			if (hiddenFCs.has(feat.fc)) continue;
			const v = overrides ? (overrides[id] ?? null) : feat[activeColumn];
			if (v !== null && v !== undefined && !isNaN(Number(v))) values.push(Number(v));
		}
		if (!values.length) {
			stats = null; currentBreaks = null;
			for (const fc of fcOrder) {
				if (map.getLayer(fcFillId(fc))) map.setPaintProperty(fcFillId(fc), 'fill-color', NO_VALUE_COLOR);
			}
			return;
		}
		let breaks: number[];
		if (currentMethod === 'quantile') breaks = quantileBreaks(values, 5);
		else if (currentMethod === 'equal') breaks = equalBreaks(values, 5);
		else { const ss = await import('simple-statistics'); breaks = ss.jenks(values, 5) as number[]; }
		const palette = PALETTES[currentPalette].colors;
		for (const fc of fcOrder) {
			if (!map.getLayer(fcFillId(fc))) continue;
			const expr = buildColorExpression(fc, activeColumn, breaks, palette, data.features, overrides);
			map.setPaintProperty(fcFillId(fc), 'fill-color', expr as maplibregl.ExpressionSpecification);
		}
		currentBreaks = breaks;
		stats = computeStats(values);
	}

	$effect(() => {
		void activeColumn; void currentPalette; void currentMethod; void hiddenFCs;
		if (mapReady) applyColors();
	});

	function toggleFC(fcName: string, visible: boolean) {
		if (!map) return;
		const next = new Set(hiddenFCs);
		if (visible) next.delete(fcName); else next.add(fcName);
		hiddenFCs = next;
		const vis = visible ? 'visible' : 'none';
		if (map.getLayer(fcFillId(fcName))) map.setLayoutProperty(fcFillId(fcName), 'visibility', vis);
		if (map.getLayer(fcLineId(fcName))) map.setLayoutProperty(fcLineId(fcName), 'visibility', vis);
	}

	$effect(() => {
		if (!mapReady || !map) return;
		const m = map; const order = fcOrder;
		for (let i = order.length - 1; i >= 0; i--) {
			const fc = order[i];
			if (m.getLayer(fcFillId(fc))) m.moveLayer(fcFillId(fc));
			if (m.getLayer(fcLineId(fc))) m.moveLayer(fcLineId(fc));
		}
	});

	let fcListEl: HTMLDivElement | null = $state(null);
	let sortable: { destroy: () => void } | null = null;
	$effect(() => {
		if (!fcListEl || fcOrder.length === 0) return;
		let cancelled = false;
		(async () => {
			const { default: Sortable } = await import('sortablejs');
			if (cancelled || !fcListEl) return;
			sortable?.destroy();
			sortable = Sortable.create(fcListEl, {
				animation: 150, filter: '[data-slot="checkbox"]', preventOnFilter: false,
				ghostClass: 'fc-row-ghost', chosenClass: 'fc-row-chosen',
				onEnd: () => {
					if (!fcListEl) return;
					fcOrder = Array.from(fcListEl.children)
						.map((el) => (el as HTMLElement).dataset.fc)
						.filter((v): v is string => !!v);
				}
			});
		})();
		return () => { cancelled = true; sortable?.destroy(); sortable = null; };
	});

	// ── Popup ─────────────────────────────────────────────────────────────────
	function renderPopupHtml(record: { name: string; fc: string; [k: string]: unknown }, featureId: string): string {
		const lines = [
			`<div class="popup-name">${escapeHtml(record.name)}</div>`,
			`<div class="popup-fc">${escapeHtml(record.fc)}</div>`,
		];
		for (const col of checkedColumns) {
			const val = resolveValue(featureId, col);
			const valStr = val === null || val === undefined ? '—' : String(val);
			const label = col.startsWith('~') ? col.slice(1) : prettyColumn(col);
			const isActive = col === activeColumn;
			if (!col.startsWith('~')) {
				const dsName = data?.col_dataset_titles?.[col];
				const temporal = data?.col_temporal?.[col];
				const meta = [dsName, temporal].filter(Boolean).join(' · ');
				if (meta) lines.push(`<div class="popup-desc">${escapeHtml(meta)}</div>`);
			}
			lines.push(`<div class="popup-row${isActive ? ' popup-row-active' : ''}"><span class="popup-col">${escapeHtml(label)}</span><span class="popup-val">${escapeHtml(valStr)}</span></div>`);
		}
		return lines.join('');
	}

	onDestroy(() => { stopTheme?.(); map?.remove(); map = null; popup?.remove(); popup = null; sortable?.destroy(); });

	function exportMapImage() {
		if (!map) return;
		const col = (activeColumn ?? 'map').replace(/^~/, '');
		const date = new Date().toISOString().slice(0, 10);
		void drawMapExport(map, {
			title: selectedFCs.map((f) => f.title || f.name).join(', ') || 'Explore',
			columnLabel: activeColumn
				? activeColumn.startsWith('~') ? activeColumn.slice(1) : prettyColumn(activeColumn)
				: null,
			palette: PALETTES[currentPalette].colors,
			breaks: currentBreaks,
			stats,
			filename: `geoquery-explore-${col}-${date}.png`
		});
	}

	function fcFeatureCount(fcName: string): number {
		if (!data) return 0;
		let count = 0;
		for (const feat of Object.values(data.features)) { if (feat.fc === fcName) count++; }
		return count;
	}
</script>

<svelte:head><title>Explore · GeoQuery</title></svelte:head>

<div class="viz-page flex flex-col h-[calc(100vh-5rem)]">
	<!-- Top bar: page title + tab switcher -->
	<div class="flex items-center justify-between border-b bg-card px-4 py-2.5 shrink-0 gap-4">
		<div>
			<h1 class="text-sm">Explore Data</h1>
			<p class="mt-0.5 text-xs text-muted-foreground">Select boundaries, then pick data to visualize.</p>
		</div>
		<div class="flex items-center gap-1 shrink-0">
			<Button
				variant="ghost"
				size="sm"
				onclick={() => (activeTab = 'map')}
				aria-pressed={activeTab === 'map'}
				class={activeTab === 'map' ? 'bg-muted text-foreground' : 'text-muted-foreground'}
			>
				<MapIcon />
				Map
			</Button>
			<Button
				variant="ghost"
				size="sm"
				onclick={() => (activeTab = 'charts')}
				aria-pressed={activeTab === 'charts'}
				class={activeTab === 'charts' ? 'bg-muted text-foreground' : 'text-muted-foreground'}
			>
				<ChartColumn />
				Charts
			</Button>
		</div>
	</div>

	<!-- Body: sidebar (map tab only) + main area -->
	<div class="flex flex-1 min-h-0">
	{#if activeTab === 'map'}
	<aside class="w-72 shrink-0 overflow-y-auto border-r bg-card">

		<!-- ── BOUNDARIES ──────────────────────────────────────────────────── -->
		<Collapsible.Root bind:open={boundariesOpen} class="border-b">
			<Collapsible.Trigger class="section-trigger">
				<ChevronDown class="section-chevron {boundariesOpen ? 'rotate-180' : ''}" />
				<span>Boundaries</span>
			</Collapsible.Trigger>
			<Collapsible.Content class="px-4 pb-4 pt-2 space-y-3">
				<!-- Chips for selected FCs -->
				{#if selectedFCs.length > 0}
					<div class="flex flex-wrap gap-1">
						{#each selectedFCs as fc}
							<span class="inline-flex items-center gap-1 rounded-full bg-primary/15 py-0.5 pr-0.5 pl-2 text-sm font-bold">
								{fc.title || fc.name}
								<Button
									variant="ghost"
									size="icon-sm"
									class="size-6 rounded-full hover:bg-primary/30"
									onclick={() => handleSelectionChange(new Set([...selectedIds].filter((id) => id !== fc.id)))}
									aria-label="Remove {fc.title || fc.name}"
								>
									<X class="size-3.5" />
								</Button>
							</span>
						{/each}
					</div>
					{#if selectedFCs.length > 1}
						<Button variant="link" size="xs" class="px-0" onclick={refitMap}>Fit map to selection</Button>
					{/if}
				{/if}

				<!-- Typeahead search (for quick add, separate from browse panel) -->
				<div class="relative">
					<Search class="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
					<Input
						type="text" placeholder="Quick search…" bind:value={fcQuery}
						aria-label="Search boundaries"
						oninput={onFcInput} onfocus={() => fcSearchOpen = true}
						onblur={() => setTimeout(() => fcSearchOpen = false, 150)}
						class="min-h-8 pl-8"
					/>
					{#if fcSearchOpen && fcSuggestions.length > 0}
						<div class="absolute left-0 right-0 top-full z-50 mt-1 rounded-md border bg-popover text-popover-foreground shadow-card">
							{#each fcSuggestions as s}
								<button class="w-full px-3 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground" onmousedown={() => addFCFromSearch(s)}>
									<span class="font-bold">{s.title || s.name}</span>
									{#if s.description}<span class="block truncate text-xs text-muted-foreground">{s.description}</span>{/if}
								</button>
							{/each}
						</div>
					{/if}
				</div>

				<!-- Browse panel (reuses the main app component) -->
				{#if layerError}
					<p class="text-xs text-danger-text mb-2">{layerError}</p>
				{/if}
				<BoundaryBrowsePanel
					allBoundaries={allBoundaries}
					selectedIds={selectedIds}
					presets={presets}
					loading={browsePanelLoading}
					onSelectionChange={handleSelectionChange}
				/>
			</Collapsible.Content>
		</Collapsible.Root>

		<!-- ── DATASETS ────────────────────────────────────────────────────── -->
		<Collapsible.Root bind:open={datasetsOpen} class="border-b">
			<Collapsible.Trigger class="section-trigger">
				<ChevronDown class="section-chevron {datasetsOpen ? 'rotate-180' : ''}" />
				<span>Datasets</span>
			</Collapsible.Trigger>
			<Collapsible.Content class="px-4 pb-4 pt-2 space-y-3">

				<!-- Data sources (PO selection) -->
				{#if selectedFCs.length === 0}
					<p class="text-xs text-muted-foreground">Select boundaries to see available data.</p>
				{:else if availableLoading}
					<p class="text-xs text-muted-foreground">Loading available data…</p>
				{:else if availableDatasets.length === 0}
					<p class="text-xs text-muted-foreground">No completed extract data for these boundaries.</p>
				{:else}
					<div class="space-y-3">
						{#each availableDatasets as ds}
							<div>
								<p class="mb-1 text-xs font-bold text-foreground">{ds.dataset_title}</p>
								{#each ds.options as opt}
									<label class="col-row">
										<Checkbox checked={checkedPoIds.has(opt.po_id)}
											onCheckedChange={(checked) => togglePo(opt.po_id, checked)} />
										<span class="flex-1 truncate">{opt.short_name}</span>
										{#if opt.description}
											<span class="max-w-[90px] truncate text-xs text-muted-foreground" title={opt.description}>{opt.description}</span>
										{/if}
									</label>
								{/each}
							</div>
						{/each}
					</div>
					{#if dataLoading}<p class="text-xs text-muted-foreground">Loading data…</p>{/if}
					{#if dataError}<p class="text-xs text-danger-text">{dataError}</p>{/if}
				{/if}

			</Collapsible.Content>
		</Collapsible.Root>

		<!-- ── STYLING ─────────────────────────────────────────────────────── -->
		<Collapsible.Root bind:open={stylingOpen} class="border-b">
			<Collapsible.Trigger class="section-trigger">
				<ChevronDown class="section-chevron {stylingOpen ? 'rotate-180' : ''}" />
				<span>Styling</span>
			</Collapsible.Trigger>
			<Collapsible.Content class="px-4 pb-4 pt-2 space-y-3">

				<!-- Boundary layer reorder -->
				{#if fcOrder.length > 0}
					<div>
						<div class="panel-title">Active Boundary Layers</div>
						<p class="mb-2 text-xs text-muted-foreground">Drag to reorder — top draws on top.</p>
						<div bind:this={fcListEl} class="space-y-0.5">
							{#each fcOrder as fc (fc)}
								<div class="fc-row" data-fc={fc}>
									<span class="fc-grip" aria-hidden="true"><GripVertical class="size-3.5" /></span>
									<Checkbox checked={!hiddenFCs.has(fc)}
										onCheckedChange={(checked) => toggleFC(fc, checked)}
										aria-label="Show {fc}" />
									<span class="fc-name" title={fc}>{fc}</span>
									{#if data}<span class="fc-count">{fcFeatureCount(fc)}</span>{/if}
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Active layers (column selector) -->
				{#if data && data.columns.length > 0}
					<div>
						<p class="panel-title mb-1">Active Data Layers</p>
						<p class="mb-2 text-xs text-muted-foreground">Check to include in popup · click name to set map layer</p>

						{#if partialCols.size > 0}
							<Alert.Root variant="warning" role="note" class="mb-2">
								<AlertCircle />
								<Alert.Description>Some columns have partial coverage — missing features show as grey.</Alert.Description>
							</Alert.Root>
						{/if}

						<div class="space-y-2">
							{#each Object.entries(data.col_groups) as [group, cols]}
								<div>
									<p class="mb-1 text-xs font-bold text-muted-foreground/70">{group}</p>
									{#each cols as col}
										<div class="col-row {activeColumn === col ? 'col-row-active' : ''}">
											<Checkbox checked={checkedColumns.has(col)}
												onCheckedChange={(checked) => setColumnChecked(col, checked)}
												aria-label="Include {prettyColumn(col)} in popup" />
											<button class="col-name flex-1 text-left"
												onclick={() => { if (checkedColumns.has(col)) activeColumn = col; }}
												title={data.col_filter_desc?.[col] || [data.col_dataset_titles[col], data.col_descriptions[col]].filter(Boolean).join(' · ') || col}
											>{prettyColumn(col)}</button>
											{#if partialCols.has(col)}<span class="text-warning-text" title="Partial coverage"><AlertCircle class="size-3.5" aria-label="Partial coverage" /></span>{/if}
											{#if activeColumn === col}<span class="active-badge">map</span>{/if}
										</div>
									{/each}
								</div>
							{/each}

							<!-- Custom indices -->
							{#each customIndices as ci}
								<div class="col-row {activeColumn === `~${ci.name}` ? 'col-row-active' : ''}">
									<Checkbox checked={checkedColumns.has(`~${ci.name}`)}
										onCheckedChange={(checked) => setColumnChecked(`~${ci.name}`, checked)}
										aria-label="Include {ci.name} in popup" />
									<button class="col-name flex-1 text-left italic"
										onclick={() => { if (checkedColumns.has(`~${ci.name}`)) activeColumn = `~${ci.name}`; }}
										title={ci.formula}>{ci.name}</button>
									{#if ci.nullCount > 0}<span class="text-warning-text" title="{ci.nullCount} null results"><AlertCircle class="size-3.5" aria-label="{ci.nullCount} null results" /></span>{/if}
									{#if activeColumn === `~${ci.name}`}<span class="active-badge">map</span>{/if}
									<Button variant="ghost" size="icon-sm" onclick={() => removeCustomIndex(ci.name)} class="size-6 text-muted-foreground hover:text-destructive" aria-label="Remove index {ci.name}"><X class="size-3.5" /></Button>
								</div>
							{/each}
						</div>

						<!-- Index builder -->
						<Button variant="link" size="xs" class="mt-1 px-0"
							onclick={() => { showIndexBuilder = !showIndexBuilder; indexError = ''; }}>
							<Plus />{showIndexBuilder ? 'Cancel' : 'Add custom index'}
						</Button>
						{#if showIndexBuilder}
							<div class="mt-2 space-y-1.5 rounded-md bg-muted p-2">
								<Input type="text" placeholder="Index name" aria-label="Index name" bind:value={indexName} class="min-h-8" />
								<textarea placeholder="e.g. [pop_count] / [land_area]" aria-label="Formula" bind:value={indexFormula}
									rows="2" class="formula-input"></textarea>
								<div class="flex flex-wrap gap-1">
									{#each data.columns as col}
										{@const meta = [data.col_dataset_titles[col], data.col_temporal[col]].filter(Boolean).join(' · ')}
										<button class="rounded-sm bg-card px-1.5 py-0.5 text-left text-muted-foreground hover:bg-accent hover:text-accent-foreground"
											onclick={() => indexFormula += `[${col}]`}>
											{#if meta}<span class="block text-xs opacity-60">{meta}</span>{/if}
											<span class="block text-xs">{prettyColumn(col)}</span>
										</button>
									{/each}
								</div>
								{#if indexError}<p class="text-xs text-danger-text">{indexError}</p>{/if}
								<Button size="sm" onclick={addCustomIndex}>Add index</Button>
							</div>
						{/if}
					</div>
				{/if}

				<div>
					<div class="panel-title" id="palette-label">Color Palette</div>
					<Select.Root type="single" bind:value={currentPalette}>
						<Select.Trigger size="sm" class="w-full" aria-labelledby="palette-label">
							{PALETTES[currentPalette].label}
						</Select.Trigger>
						<Select.Content>
							{#each Object.entries(PALETTES) as [key, p] (key)}
								<Select.Item value={key} label={p.label} />
							{/each}
						</Select.Content>
					</Select.Root>
				</div>
				<div>
					<div class="panel-title" id="method-label">Classification</div>
					<Select.Root type="single" value={currentMethod} onValueChange={(v) => (currentMethod = v as typeof currentMethod)}>
						<Select.Trigger size="sm" class="w-full" aria-labelledby="method-label">
							{METHOD_LABELS[currentMethod]}
						</Select.Trigger>
						<Select.Content>
							{#each Object.entries(METHOD_LABELS) as [key, label] (key)}
								<Select.Item value={key} {label} />
							{/each}
						</Select.Content>
					</Select.Root>
				</div>

			</Collapsible.Content>
		</Collapsible.Root>

		<!-- ── INFORMATION ─────────────────────────────────────────────────── -->
		<Collapsible.Root bind:open={infoOpen} class="border-b">
			<Collapsible.Trigger class="section-trigger">
				<ChevronDown class="section-chevron {infoOpen ? 'rotate-180' : ''}" />
				<span>Information</span>
			</Collapsible.Trigger>
			<Collapsible.Content class="px-4 pb-4 pt-2 space-y-4">

				<!-- Legend -->
				<div>
					<div class="panel-title">Legend</div>
					{#if currentBreaks && activeColumn}
						<p class="mb-1.5 truncate text-sm text-muted-foreground">
							{activeColumn.startsWith('~') ? activeColumn.slice(1) : prettyColumn(activeColumn)}
						</p>
						<MapLegend palette={PALETTES[currentPalette].colors} breaks={currentBreaks} />
					{:else}
						<p class="text-sm text-muted-foreground">Select a column to see legend.</p>
					{/if}
				</div>

				<!-- Stats -->
				<div>
					<div class="panel-title">Statistics</div>
					<div class="stats-grid">
						<div><div class="stat-label">Min</div><div class="stat-value">{stats ? fmt(stats.min) : '—'}</div></div>
						<div><div class="stat-label">Max</div><div class="stat-value">{stats ? fmt(stats.max) : '—'}</div></div>
						<div><div class="stat-label">Mean</div><div class="stat-value">{stats ? fmt(stats.mean) : '—'}</div></div>
						<div><div class="stat-label">Features</div><div class="stat-value">{stats?.n ?? '—'}</div></div>
					</div>
				</div>

			</Collapsible.Content>
		</Collapsible.Root>
	</aside>
	{/if}

	<!-- Main content -->
	<div class="relative flex-1 overflow-hidden">
			<div
				bind:this={mapContainer}
				class="h-full w-full {activeTab !== 'map' ? 'invisible pointer-events-none' : ''}"
			></div>
			{#if mapReady && activeTab === 'map'}
				<Button
					variant="outline"
					size="sm"
					onclick={exportMapImage}
					class="absolute right-2 top-2 z-10 bg-card shadow-card"
					title="Save map as PNG"
				>
					<Download />
					Save image
				</Button>
			{/if}
			{#if selectedFCs.length === 0 && activeTab === 'map'}
				<div class="pointer-events-none absolute inset-0 flex items-center justify-center">
					<div class="card-surface px-6 py-4 text-center">
						<p class="text-sm font-bold text-foreground">Select boundaries from the sidebar to get started.</p>
					</div>
				</div>
			{/if}
			{#if chartsVisited}
				<div class="absolute inset-0 z-10 bg-background" hidden={activeTab !== 'charts'}>
					{#if data}
						{#await loadChartPanel() then { default: ChartPanel }}
							<ChartPanel {data} />
						{/await}
					{:else}
						<div class="flex h-full items-center justify-center text-sm text-muted-foreground">
							Select boundaries and datasets to see charts.
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>

<style>
	:global(.section-trigger) {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 9px 16px;
		background: var(--band);
		font-family: var(--font-heading);
		font-size: var(--text-sm);
		font-weight: 700;
		color: var(--foreground);
		cursor: pointer;
		transition: background 0.1s;
	}
	:global(.section-trigger:hover) { background: var(--accent); }
	:global(.section-chevron) {
		height: 16px; width: 16px;
		color: var(--muted-foreground);
		flex-shrink: 0;
		transition: transform 0.15s ease;
	}

	.panel-title {
		font-family: var(--font-heading); font-size: var(--text-sm); font-weight: 700;
		color: var(--foreground); margin-bottom: 6px;
	}
	.formula-input {
		width: 100%; min-height: 4rem; resize: none; padding: 6px 10px;
		border: 1px solid var(--input); border-radius: var(--radius);
		background: var(--background); color: var(--foreground);
		font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: var(--text-field);
	}

	.col-row { display: flex; align-items: center; gap: 6px; padding: 2px 4px; border-radius: 4px; font-size: var(--text-sm); }
	label.col-row { cursor: pointer; }
	.col-row:hover { background: var(--muted); }
	.col-row-active { background: var(--accent); }
	.col-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--foreground); background: none; border: none; padding: 0; font-size: inherit; cursor: pointer; }
	.active-badge {
		font-family: var(--font-ui); font-size: var(--text-xs); font-weight: 700; line-height: 1.4;
		color: var(--primary-foreground); background: var(--primary); border-radius: 9999px; padding: 0 6px; flex-shrink: 0;
	}

	.stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
	.stat-label { font-size: var(--text-xs); color: var(--muted-foreground); }
	.stat-value { font-family: var(--font-ui); font-size: var(--text-sm); font-weight: 700; color: var(--foreground); font-variant-numeric: tabular-nums; }

	.fc-row { display: flex; align-items: center; gap: 6px; padding: 3px 2px; border-radius: 4px; font-size: var(--text-sm); cursor: grab; user-select: none; }
	.fc-row:active { cursor: grabbing; }
	.fc-row:hover { background: var(--muted); }
	.fc-row .fc-grip { flex-shrink: 0; color: var(--muted-foreground); display: inline-flex; }
	.fc-row .fc-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
	.fc-row .fc-count { font-family: var(--font-ui); font-size: var(--text-xs); font-weight: 700; color: var(--muted-foreground); flex-shrink: 0; font-variant-numeric: tabular-nums; }

	:global(.fc-row-ghost) { opacity: 0.4; background: var(--accent); }
	:global(.fc-row-chosen) { background: var(--muted); }
</style>
