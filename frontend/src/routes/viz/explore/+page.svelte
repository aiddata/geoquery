<script lang="ts">
	import { onMount, onDestroy, tick } from 'svelte';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { layers, namedFlavor } from '@protomaps/basemaps';
	import * as Collapsible from '$lib/components/ui/collapsible';
	import BoundaryBrowsePanel from '$lib/components/map/BoundaryBrowsePanel.svelte';
	import {
		searchBoundaries, fetchBoundaryPresets, fetchExploreAvailable, fetchExploreData, fetchConfig,
		boundaryTileUrl,
		type BoundaryResult, type BoundaryPreset, type ExploreDataset, type VizPayload,
	} from '$lib/api';
	import {
		PALETTES, quantileBreaks, equalBreaks, buildColorExpression,
		fmt, prettyColumn, escapeHtml, computeStats,
	} from '$lib/viz';
	import { parseFormula, evaluateFormula, formulaColumns } from '$lib/formula';
	import { GripVertical, AlertCircle, Plus, X, Search, ChevronDown } from '@lucide/svelte';

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
			void refreshAvailable();
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
	let currentPalette = $state<string>('YlOrRd');
	let currentMethod = $state<'quantile' | 'equal' | 'jenks'>('quantile');
	let currentBreaks = $state<number[] | null>(null);
	let hiddenFCs = $state<Set<string>>(new Set());
	let fcOrder = $state<string[]>([]);
	let stats = $state<{ min: number; max: number; mean: number; n: number } | null>(null);
	let popup: maplibregl.Popup | null = null;

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
		const missing = formulaColumns(expr).filter((c) => !data?.columns.includes(c));
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

	// ── Map init ──────────────────────────────────────────────────────────────
	onMount(async () => {
		// Load all boundaries and presets in parallel
		const [allB, p] = await Promise.allSettled([
			searchBoundaries('', 0),
			fetchBoundaryPresets(),
		]);
		allBoundaries = allB.status === 'fulfilled' ? allB.value : [];
		presets = p.status === 'fulfilled' ? p.value : [];
		browsePanelLoading = false;

		const config = await fetchConfig();
		map = new maplibregl.Map({
			container: mapContainer,
			style: {
				version: 8,
				glyphs: 'https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf',
				sprite: 'https://protomaps.github.io/basemaps-assets/sprites/v4/light',
				sources: { protomaps: {
					type: 'vector',
					tiles: [`https://api.protomaps.com/tiles/v4/{z}/{x}/{y}.mvt?key=${config.protomaps_api_key}`],
					maxzoom: 15,
					attribution: '<a href="https://protomaps.com">Protomaps</a> &copy; <a href="https://openstreetmap.org">OpenStreetMap</a>'
				}},
				layers: layers('protomaps', namedFlavor('light'), { lang: 'en' })
			},
			center: [0, 20], zoom: 2
		});
		map.on('load', () => { mapReady = true; });
	});

	async function addFCToMap(fc: BoundaryResult) {
		if (!map) return;
		if (!mapReady) await new Promise<void>((r) => { map!.once('load', () => r()); });
		if (map.getSource(`fc-${fc.name}`)) return;

		map.addSource(`fc-${fc.name}`, {
			type: 'vector', tiles: [boundaryTileUrl(fc.name)],
			minzoom: 0, maxzoom: 12, promoteId: { [fc.name]: 'id' }
		});
		map.addLayer({
			id: `fc-fill-${fc.name}`, type: 'fill',
			source: `fc-${fc.name}`, 'source-layer': fc.name,
			paint: {
				'fill-color': ['case', ['boolean', ['feature-state', 'hover'], false], '#fff', '#cbd5e1'],
				'fill-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.9, 0.75]
			}
		});
		map.addLayer({
			id: `fc-line-${fc.name}`, type: 'line',
			source: `fc-${fc.name}`, 'source-layer': fc.name,
			paint: { 'line-color': '#334155', 'line-width': 0.75 }
		});

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
		if (map.getLayer(`fc-fill-${fcName}`)) map.removeLayer(`fc-fill-${fcName}`);
		if (map.getLayer(`fc-line-${fcName}`)) map.removeLayer(`fc-line-${fcName}`);
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
				if (map.getLayer(`fc-fill-${fc}`)) map.setPaintProperty(`fc-fill-${fc}`, 'fill-color', '#cbd5e1');
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
				if (map.getLayer(`fc-fill-${fc}`)) map.setPaintProperty(`fc-fill-${fc}`, 'fill-color', '#cbd5e1');
			}
			return;
		}
		let breaks: number[];
		if (currentMethod === 'quantile') breaks = quantileBreaks(values, 5);
		else if (currentMethod === 'equal') breaks = equalBreaks(values, 5);
		else { const ss = await import('simple-statistics'); breaks = ss.jenks(values, 5) as number[]; }
		const palette = PALETTES[currentPalette].colors;
		for (const fc of fcOrder) {
			if (!map.getLayer(`fc-fill-${fc}`)) continue;
			const expr = buildColorExpression(fc, activeColumn, breaks, palette, data.features, overrides);
			map.setPaintProperty(`fc-fill-${fc}`, 'fill-color', [
				'case', ['boolean', ['feature-state', 'hover'], false], '#fff', expr
			]);
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
		if (map.getLayer(`fc-fill-${fcName}`)) map.setLayoutProperty(`fc-fill-${fcName}`, 'visibility', vis);
		if (map.getLayer(`fc-line-${fcName}`)) map.setLayoutProperty(`fc-line-${fcName}`, 'visibility', vis);
	}

	$effect(() => {
		if (!mapReady || !map) return;
		const m = map; const order = fcOrder;
		for (let i = order.length - 1; i >= 0; i--) {
			const fc = order[i];
			if (m.getLayer(`fc-fill-${fc}`)) m.moveLayer(`fc-fill-${fc}`);
			if (m.getLayer(`fc-line-${fc}`)) m.moveLayer(`fc-line-${fc}`);
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
				animation: 150, filter: 'input[type="checkbox"]', preventOnFilter: false,
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

	onDestroy(() => { map?.remove(); map = null; popup?.remove(); popup = null; sortable?.destroy(); });

	function fcFeatureCount(fcName: string): number {
		if (!data) return 0;
		let count = 0;
		for (const feat of Object.values(data.features)) { if (feat.fc === fcName) count++; }
		return count;
	}
</script>

<svelte:head><title>Explore · GeoQuery</title></svelte:head>

<div class="viz-page flex h-[calc(100vh-5rem)]">
	<!-- Sidebar -->
	<aside class="w-72 shrink-0 overflow-y-auto border-r bg-card">

		<!-- Page header -->
		<div class="border-b border-slate-200 bg-slate-50 px-4 py-3">
			<p class="text-sm font-semibold text-slate-800">Explore Data</p>
			<p class="mt-0.5 text-[11px] text-slate-500">Select boundaries, then pick data to visualize.</p>
		</div>

		<!-- ── BOUNDARIES ──────────────────────────────────────────────────── -->
		<Collapsible.Root bind:open={boundariesOpen} class="border-b border-slate-200">
			<Collapsible.Trigger class="section-trigger">
				<ChevronDown class="section-chevron {boundariesOpen ? 'rotate-180' : ''}" />
				<span>Boundaries</span>
			</Collapsible.Trigger>
			<Collapsible.Content class="px-4 pb-4 pt-2 space-y-3">
				<!-- Chips for selected FCs -->
				{#if selectedFCs.length > 0}
					<div class="flex flex-wrap gap-1">
						{#each selectedFCs as fc}
							<span class="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-800">
								{fc.title || fc.name}
								<button onclick={() => handleSelectionChange(new Set([...selectedIds].filter((id) => id !== fc.id)))}
									class="ml-0.5 text-blue-500 hover:text-blue-800">
									<X class="h-2.5 w-2.5" />
								</button>
							</span>
						{/each}
					</div>
					{#if selectedFCs.length > 1}
						<button class="text-[11px] text-primary hover:underline" onclick={refitMap}>Fit map to selection</button>
					{/if}
				{/if}

				<!-- Typeahead search (for quick add, separate from browse panel) -->
				<div class="relative">
					<Search class="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
					<input
						type="text" placeholder="Quick search…" bind:value={fcQuery}
						oninput={onFcInput} onfocus={() => fcSearchOpen = true}
						onblur={() => setTimeout(() => fcSearchOpen = false, 150)}
						class="w-full rounded-md border py-1.5 pl-8 pr-3 text-[12px] bg-white text-slate-900 outline-none focus:ring-2 focus:ring-blue-400"
					/>
					{#if fcSearchOpen && fcSuggestions.length > 0}
						<div class="absolute left-0 right-0 top-full z-50 mt-1 rounded-md border bg-white shadow-lg">
							{#each fcSuggestions as s}
								<button class="w-full px-3 py-2 text-left text-[12px] hover:bg-accent" onmousedown={() => addFCFromSearch(s)}>
									<span class="font-medium">{s.title || s.name}</span>
									{#if s.description}<span class="block truncate text-[10px] text-muted-foreground">{s.description}</span>{/if}
								</button>
							{/each}
						</div>
					{/if}
				</div>

				<!-- Browse panel (reuses the main app component) -->
				{#if layerError}
					<p class="text-xs text-destructive mb-2">{layerError}</p>
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
		<Collapsible.Root bind:open={datasetsOpen} class="border-b border-slate-200">
			<Collapsible.Trigger class="section-trigger">
				<ChevronDown class="section-chevron {datasetsOpen ? 'rotate-180' : ''}" />
				<span>Datasets</span>
			</Collapsible.Trigger>
			<Collapsible.Content class="px-4 pb-4 pt-2 space-y-3">

				<!-- Data sources (PO selection) -->
				{#if selectedFCs.length === 0}
					<p class="text-[11px] text-muted-foreground">Select boundaries to see available data.</p>
				{:else if availableLoading}
					<p class="text-[11px] text-muted-foreground">Loading available data…</p>
				{:else if availableDatasets.length === 0}
					<p class="text-[11px] text-muted-foreground">No completed extract data for these boundaries.</p>
				{:else}
					<div class="space-y-3">
						{#each availableDatasets as ds}
							<div>
								<p class="mb-1 text-[11px] font-semibold text-foreground">{ds.dataset_title}</p>
								{#each ds.options as opt}
									<label class="col-row">
										<input type="checkbox" checked={checkedPoIds.has(opt.po_id)}
											onchange={(e) => togglePo(opt.po_id, (e.target as HTMLInputElement).checked)} />
										<span class="flex-1 truncate text-[12px]">{opt.short_name}</span>
										{#if opt.description}
											<span class="max-w-[90px] truncate text-[10px] text-muted-foreground" title={opt.description}>{opt.description}</span>
										{/if}
									</label>
								{/each}
							</div>
						{/each}
					</div>
					{#if dataLoading}<p class="text-[11px] text-muted-foreground">Loading data…</p>{/if}
					{#if dataError}<p class="text-[11px] text-destructive">{dataError}</p>{/if}
				{/if}

			</Collapsible.Content>
		</Collapsible.Root>

		<!-- ── STYLING ─────────────────────────────────────────────────────── -->
		<Collapsible.Root bind:open={stylingOpen} class="border-b border-slate-200">
			<Collapsible.Trigger class="section-trigger">
				<ChevronDown class="section-chevron {stylingOpen ? 'rotate-180' : ''}" />
				<span>Styling</span>
			</Collapsible.Trigger>
			<Collapsible.Content class="px-4 pb-4 pt-2 space-y-3">

				<!-- Boundary layer reorder -->
				{#if fcOrder.length > 0}
					<div>
						<div class="panel-title">Active Boundary Layers</div>
						<p class="mb-2 text-[10px] text-muted-foreground">Drag to reorder — top draws on top.</p>
						<div bind:this={fcListEl} class="space-y-0.5">
							{#each fcOrder as fc (fc)}
								<div class="fc-row" data-fc={fc}>
									<span class="fc-grip"><GripVertical class="h-3.5 w-3.5" /></span>
									<input type="checkbox" checked={!hiddenFCs.has(fc)}
										onchange={(e) => toggleFC(fc, (e.target as HTMLInputElement).checked)} />
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
						<p class="mb-2 text-[10px] text-muted-foreground">Check to include in popup · click name to set map layer</p>

						{#if partialCols.size > 0}
							<div class="mb-2 flex items-start gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5">
								<AlertCircle class="mt-0.5 h-3 w-3 shrink-0 text-amber-500" />
								<p class="text-[11px] text-amber-700">Some columns have partial coverage — missing features show as grey.</p>
							</div>
						{/if}

						<div class="space-y-2">
							{#each Object.entries(data.col_groups) as [group, cols]}
								<div>
									<p class="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">{group}</p>
									{#each cols as col}
										<label class="col-row {activeColumn === col ? 'col-row-active' : ''}">
											<input type="checkbox" checked={checkedColumns.has(col)}
												onchange={(e) => {
													const next = new Set(checkedColumns);
													if ((e.target as HTMLInputElement).checked) { next.add(col); activeColumn = col; }
													else { next.delete(col); if (activeColumn === col) activeColumn = [...next][0] ?? null; }
													checkedColumns = next;
												}} />
											<button class="col-name flex-1 text-left"
												onclick={() => { if (checkedColumns.has(col)) activeColumn = col; }}
												title={[data.col_dataset_titles[col], data.col_descriptions[col]].filter(Boolean).join(' · ') || col}
											>{prettyColumn(col)}</button>
											{#if partialCols.has(col)}<span class="text-[10px] text-amber-500" title="Partial coverage">⚠</span>{/if}
											{#if activeColumn === col}<span class="active-badge">map</span>{/if}
										</label>
									{/each}
								</div>
							{/each}

							<!-- Custom indices -->
							{#each customIndices as ci}
								<label class="col-row {activeColumn === `~${ci.name}` ? 'col-row-active' : ''}">
									<input type="checkbox" checked={checkedColumns.has(`~${ci.name}`)}
										onchange={(e) => {
											const key = `~${ci.name}`; const next = new Set(checkedColumns);
											if ((e.target as HTMLInputElement).checked) { next.add(key); activeColumn = key; }
											else { next.delete(key); if (activeColumn === key) activeColumn = [...next][0] ?? null; }
											checkedColumns = next;
										}} />
									<button class="col-name flex-1 text-left italic"
										onclick={() => { if (checkedColumns.has(`~${ci.name}`)) activeColumn = `~${ci.name}`; }}
										title={ci.formula}>{ci.name}</button>
									{#if ci.nullCount > 0}<span class="text-[10px] text-amber-500" title="{ci.nullCount} null results">⚠</span>{/if}
									{#if activeColumn === `~${ci.name}`}<span class="active-badge">map</span>{/if}
									<button onclick={() => removeCustomIndex(ci.name)} class="ml-1 text-muted-foreground hover:text-destructive"><X class="h-3 w-3" /></button>
								</label>
							{/each}
						</div>

						<!-- Index builder -->
						<button class="mt-2 flex items-center gap-1 text-[11px] text-primary hover:underline"
							onclick={() => { showIndexBuilder = !showIndexBuilder; indexError = ''; }}>
							<Plus class="h-3 w-3" />{showIndexBuilder ? 'Cancel' : 'Add custom index'}
						</button>
						{#if showIndexBuilder}
							<div class="mt-2 space-y-1.5 rounded-md border bg-muted/30 p-2">
								<input type="text" placeholder="Index name" bind:value={indexName} class="viz-input" />
								<textarea placeholder="e.g. [pop_count] / [land_area]" bind:value={indexFormula}
									rows="2" class="viz-input resize-none font-mono text-[11px]"></textarea>
								<div class="flex flex-wrap gap-1">
									{#each data.columns as col}
										{@const meta = [data.col_dataset_titles[col], data.col_temporal[col]].filter(Boolean).join(' · ')}
										<button class="rounded bg-muted px-1.5 py-0.5 text-left text-muted-foreground hover:bg-accent"
											onclick={() => indexFormula += `[${col}]`}>
											{#if meta}<span class="block text-[9px] opacity-60">{meta}</span>{/if}
											<span class="block text-[10px]">{prettyColumn(col)}</span>
										</button>
									{/each}
								</div>
								{#if indexError}<p class="text-[11px] text-destructive">{indexError}</p>{/if}
								<button class="viz-btn-primary" onclick={addCustomIndex}>Add index</button>
							</div>
						{/if}
					</div>
				{/if}

				<div>
					<div class="panel-title">Color Palette</div>
					<select bind:value={currentPalette} class="viz-select">
						{#each Object.entries(PALETTES) as [key, p]}<option value={key}>{p.label}</option>{/each}
					</select>
				</div>
				<div>
					<div class="panel-title">Classification</div>
					<select bind:value={currentMethod} class="viz-select">
						<option value="quantile">Quantile</option>
						<option value="equal">Equal interval</option>
						<option value="jenks">Natural Breaks (Jenks)</option>
					</select>
				</div>

			</Collapsible.Content>
		</Collapsible.Root>

		<!-- ── INFORMATION ─────────────────────────────────────────────────── -->
		<Collapsible.Root bind:open={infoOpen} class="border-b border-slate-200">
			<Collapsible.Trigger class="section-trigger">
				<ChevronDown class="section-chevron {infoOpen ? 'rotate-180' : ''}" />
				<span>Information</span>
			</Collapsible.Trigger>
			<Collapsible.Content class="px-4 pb-4 pt-2 space-y-4">

				<!-- Legend -->
				<div>
					<div class="panel-title">Legend</div>
					{#if currentBreaks && activeColumn}
						{@const palette = PALETTES[currentPalette].colors}
						<p class="mb-1.5 truncate text-[10px] font-medium text-muted-foreground">
							{activeColumn.startsWith('~') ? activeColumn.slice(1) : prettyColumn(activeColumn)}
						</p>
						<div class="space-y-1">
							{#each palette as color, i}
								<div class="legend-item"><span class="legend-swatch" style="background:{color}"></span><span>{fmt(currentBreaks[i])} – {fmt(currentBreaks[i+1])}</span></div>
							{/each}
							<div class="legend-item legend-nodata"><span class="legend-swatch" style="background:#cbd5e1"></span><span>No data</span></div>
						</div>
					{:else}
						<p class="text-[11px] text-muted-foreground">Select a column to see legend.</p>
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

	<!-- Map -->
	<div class="relative flex-1">
		<div bind:this={mapContainer} class="h-full w-full"></div>
		{#if selectedFCs.length === 0}
			<div class="pointer-events-none absolute inset-0 flex items-center justify-center">
				<div class="rounded-lg border bg-white/90 px-6 py-4 text-center shadow-sm backdrop-blur-sm">
					<p class="text-sm font-medium text-foreground">Select boundaries from the sidebar to get started.</p>
				</div>
			</div>
		{/if}
	</div>
</div>

<style>
	:global(.section-trigger) {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 9px 16px;
		background: #f8fafc;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #64748b;
		cursor: pointer;
		transition: background 0.1s, color 0.1s;
	}
	:global(.section-trigger:hover) { background: #f1f5f9; color: #334155; }
	.section-chevron {
		height: 13px; width: 13px;
		color: #94a3b8;
		flex-shrink: 0;
		transition: transform 0.15s ease;
	}

	.panel-title { font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:0.07em; color:#94a3b8; margin-bottom:6px; }
	.viz-select { width:100%; padding:5px 8px; border:1px solid #e2e8f0; border-radius:6px; font-size:12px; background:#fff; color:#1e293b; cursor:pointer; }
	.viz-select:focus { outline:2px solid #3b82f6; outline-offset:-1px; }
	.viz-input { width:100%; padding:4px 7px; border:1px solid #e2e8f0; border-radius:5px; font-size:12px; background:#fff; color:#1e293b; }
	.viz-input:focus { outline:2px solid #3b82f6; outline-offset:-1px; }
	.viz-btn-primary { padding:4px 10px; background:#3b82f6; color:#fff; border-radius:5px; font-size:12px; font-weight:500; }
	.viz-btn-primary:hover { background:#2563eb; }

	.col-row { display:flex; align-items:center; gap:5px; padding:2px 4px; border-radius:4px; font-size:12px; cursor:pointer; }
	.col-row:hover { background:#f8fafc; }
	.col-row-active { background:#eff6ff; }
	.col-row input[type="checkbox"] { flex-shrink:0; accent-color:#3b82f6; cursor:pointer; }
	.col-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#1e293b; background:none; border:none; padding:0; font-size:inherit; cursor:pointer; }
	.active-badge { font-size:9px; font-weight:600; text-transform:uppercase; letter-spacing:0.04em; color:#2563eb; background:#dbeafe; border-radius:3px; padding:1px 5px; flex-shrink:0; line-height:1.4; }

	.stats-grid { display:grid; grid-template-columns:1fr 1fr; gap:6px; }
	.stat-label { font-size:9px; text-transform:uppercase; letter-spacing:0.06em; color:#94a3b8; }
	.stat-value { font-size:13px; font-weight:500; color:#1e293b; font-variant-numeric:tabular-nums; }

	.legend-item { display:flex; align-items:center; gap:8px; font-size:11px; color:#475569; font-variant-numeric:tabular-nums; }
	.legend-item.legend-nodata { opacity:0.55; }
	.legend-swatch { width:13px; height:13px; border-radius:2px; flex-shrink:0; border:1px solid rgba(0,0,0,0.08); }

	.fc-row { display:flex; align-items:center; gap:6px; padding:3px 2px; border-radius:4px; font-size:12px; cursor:grab; user-select:none; }
	.fc-row:active { cursor:grabbing; }
	.fc-row:hover { background:#f8fafc; }
	.fc-row input[type="checkbox"] { flex-shrink:0; cursor:pointer; accent-color:#3b82f6; }
	.fc-row .fc-grip { flex-shrink:0; color:#cbd5e1; display:inline-flex; }
	.fc-row .fc-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; min-width:0; }
	.fc-row .fc-count { font-size:10px; color:#94a3b8; flex-shrink:0; }

	:global(.fc-row-ghost) { opacity:0.4; background:#eff6ff; }
	:global(.fc-row-chosen) { background:#f1f5f9; }
	:global(.maplibregl-popup-content) { font-size:12px; padding:8px 10px; border-radius:6px; }
	:global(.popup-name) { font-weight:600; color:#0f172a; }
	:global(.popup-fc) { font-size:10px; color:#94a3b8; margin-bottom:4px; }
	:global(.popup-row) { display:flex; gap:8px; justify-content:space-between; margin-top:2px; }
	:global(.popup-row-active .popup-col) { color:#3b82f6; }
	:global(.popup-col) { color:#64748b; }
	:global(.popup-val) { font-weight:500; color:#1e293b; font-variant-numeric:tabular-nums; }
	:global(.popup-desc) { font-size:10px; color:#94a3b8; margin-top:2px; }
</style>
