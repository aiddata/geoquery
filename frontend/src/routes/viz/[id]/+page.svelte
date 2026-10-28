<script lang="ts">
	import { onMount, onDestroy, tick } from 'svelte';
	import { get } from 'svelte/store';
	import { page } from '$app/state';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { fetchVisualizationData, boundaryTileUrl, type VisualizationData } from '$lib/api';
	import { protomapsApiKey } from '$lib/map/protomapsKey';
	import {
		PALETTES, DEFAULT_PALETTE, NO_VALUE_COLOR, quantileBreaks, equalBreaks, buildColorExpression,
		fmt, prettyColumn, escapeHtml, computeStats,
	} from '$lib/viz';
	import { basemapStyle, followTheme } from '$lib/map/basemap';
	import { addChoroplethLayers, refreshChoroplethTheme, fcFillId, fcLineId } from '$lib/map/choropleth';
	import { exportMapImage as drawMapExport } from '$lib/map/exportMapImage';
	import { resolvedTheme } from '$lib/stores/theme';
	import { Button } from '$lib/components/ui/button';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Input } from '$lib/components/ui/input';
	import * as Select from '$lib/components/ui/select';
	import MapLegend from '$lib/components/viz/MapLegend.svelte';
	import { parseFormula, evaluateFormula, formulaColumns } from '$lib/formula';
	import { GripVertical, AlertCircle, Plus, X, Download, ChartColumn, Map as MapIcon } from '@lucide/svelte';

	const requestId = page.params.id;

	// ── State ────────────────────────────────────────────────────────────────
	let data = $state<VisualizationData | null>(null);
	let loading = $state(true);
	let loadError = $state('');

	let mapContainer: HTMLDivElement;
	let map: maplibregl.Map | null = $state(null);
	let mapReady = $state(false);

	// Multi-column: set of checked columns; activeColumn is what the choropleth shows.
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

	let activeTab = $state<'map' | 'charts'>('map');
	// Charts load on the first visit to their tab, then stay mounted so configured cards survive tab switches
	let chartsVisited = $state(false);
	$effect(() => {
		if (activeTab === 'charts') chartsVisited = true;
	});
	const loadChartPanel = () => import('$lib/components/viz/ChartPanel.svelte');

	// ── Custom indices ────────────────────────────────────────────────────────
	interface CustomIndex {
		name: string;
		formula: string;
		values: Record<string, number | null>;
		nullCount: number;
	}
	let customIndices = $state<CustomIndex[]>([]);
	let showIndexBuilder = $state(false);
	let indexName = $state('');
	let indexFormula = $state('');
	let indexError = $state('');

	function resolveValue(featureId: string, col: string): unknown {
		if (col.startsWith('~')) {
			return customIndices.find((c) => `~${c.name}` === col)?.values[featureId] ?? null;
		}
		return data?.features[featureId]?.[col] ?? null;
	}

	function addCustomIndex() {
		indexError = '';
		if (!indexName.trim()) { indexError = 'Name required.'; return; }
		if (customIndices.some((c) => c.name === indexName.trim())) {
			indexError = 'Name already used.'; return;
		}
		let expr;
		try { expr = parseFormula(indexFormula); } catch (e) {
			indexError = e instanceof Error ? e.message : 'Parse error'; return;
		}
		const cols = formulaColumns(expr);
		const allCols = new Set([...(data?.columns ?? []), ...customIndices.map((c) => c.name)]);
		const missing = cols.filter((c) => !allCols.has(c));
		if (missing.length) { indexError = `Unknown columns: ${missing.join(', ')}`; return; }

		const values: Record<string, number | null> = {};
		let nullCount = 0;
		for (const [id, feat] of Object.entries(data?.features ?? {})) {
			const v = evaluateFormula(expr, feat as Record<string, unknown>);
			values[id] = v;
			if (v === null) nullCount++;
		}

		const name = indexName.trim();
		customIndices = [...customIndices, { name, formula: indexFormula, values, nullCount }];
		checkedColumns = new Set([...checkedColumns, `~${name}`]);
		activeColumn = `~${name}`;
		indexName = '';
		indexFormula = '';
		showIndexBuilder = false;
	}

	function removeCustomIndex(name: string) {
		customIndices = customIndices.filter((c) => c.name !== name);
		const key = `~${name}`;
		const next = new Set(checkedColumns);
		next.delete(key);
		checkedColumns = next;
		if (activeColumn === key) activeColumn = [...checkedColumns][0] ?? null;
	}

	function setColumnChecked(key: string, checked: boolean) {
		const next = new Set(checkedColumns);
		if (checked) {
			next.add(key);
			activeColumn = key;
		} else {
			next.delete(key);
			if (activeColumn === key) activeColumn = [...next][0] ?? null;
		}
		checkedColumns = next;
	}

	function insertColumn(col: string) {
		indexFormula += `[${col}]`;
	}

	// Styling carried in the URL, so a link can reproduce an exact view.
	// The MCP server hands these links back with every map and table it
	// returns, so the page must land on the same picture the assistant just
	// described — see backend/mcp_server/tools/explore.py:viz_url.
	function applyUrlParams(result: { columns: string[] }) {
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
		if (col && (result.columns.includes(col) || col.startsWith('~'))) {
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

	// ── Data load ────────────────────────────────────────────────────────────
	onMount(async () => {
		try {
			const result = await fetchVisualizationData(requestId);
			data = result;
			const firstCol = result.columns[0] ?? null;
			if (firstCol) {
				checkedColumns = new Set([firstCol]);
				activeColumn = firstCol;
			}
			fcOrder = [...result.fc_names].reverse();
			applyUrlParams(result);
		} catch (err) {
			loadError = err instanceof Error ? err.message : 'Failed to load visualization.';
		} finally {
			loading = false;
		}
	});

	// ── Map init ─────────────────────────────────────────────────────────────
	$effect(() => {
		if (!data || !mapContainer || map) return;
		void initMap();
	});

	async function initMap() {
		const key = await protomapsApiKey();
		map = new maplibregl.Map({
			container: mapContainer,
			preserveDrawingBuffer: true,
			style: basemapStyle(get(resolvedTheme), key),
			center: [0, 20],
			zoom: 2
		});

		map.on('load', () => {
			addFeatureLayers();
			setupHover();
			fitToBbox();
			mapReady = true;
			void applyColors();
		});

		stopTheme = followTheme(map, key, () => {
			if (map && data) refreshChoroplethTheme(map, data.fc_names);
		});
	}

	function addFeatureLayers() {
		if (!map || !data) return;
		for (const fc of data.fc_names) {
			addChoroplethLayers(map, fc, boundaryTileUrl(fc));
		}
	}

	function fitToBbox() {
		if (!map || !data?.bbox) return;
		const [w, s, e, n] = data.bbox;
		map.fitBounds([[w, s], [e, n]], { padding: 40, maxZoom: 10, duration: 0 });
	}

	async function applyColors() {
		if (!map || !mapReady || !data || !activeColumn) return;

		const overrides = activeColumn.startsWith('~')
			? customIndices.find((c) => `~${c.name}` === activeColumn)?.values
			: undefined;

		const values: number[] = [];
		for (const [id, feat] of Object.entries(data.features)) {
			if (hiddenFCs.has(feat.fc)) continue;
			const v = overrides ? (overrides[id] ?? null) : feat[activeColumn];
			if (v !== null && v !== undefined && !isNaN(Number(v))) values.push(Number(v));
		}

		if (values.length === 0) {
			stats = null; currentBreaks = null;
			for (const fc of data.fc_names) {
				map.setPaintProperty(fcFillId(fc), 'fill-color', NO_VALUE_COLOR);
			}
			return;
		}

		let breaks: number[];
		if (currentMethod === 'quantile') breaks = quantileBreaks(values, 5);
		else if (currentMethod === 'equal') breaks = equalBreaks(values, 5);
		else { const ss = await import('simple-statistics'); breaks = ss.jenks(values, 5) as number[]; }

		const palette = PALETTES[currentPalette].colors;
		for (const fc of data.fc_names) {
			const expr = buildColorExpression(fc, activeColumn, breaks, palette, data.features, overrides);
			map.setPaintProperty(fcFillId(fc), 'fill-color', expr as maplibregl.ExpressionSpecification);
		}
		currentBreaks = breaks;
		stats = computeStats(values);
	}

	$effect(() => {
		void activeColumn; void currentPalette; void currentMethod; void hiddenFCs;
		if (mapReady) void applyColors();
	});

	// The map container has no layout while it sits behind the inactive tab on
	// first paint, so MapLibre can size its canvas to 0. Resize once the map is
	// ready and whenever the map tab is reactivated to keep the canvas correct.
	$effect(() => {
		if (activeTab === 'map' && map && mapReady) {
			requestAnimationFrame(() => map?.resize());
		}
	});

	function toggleFC(fc: string, visible: boolean) {
		if (!map) return;
		const next = new Set(hiddenFCs);
		if (visible) next.delete(fc); else next.add(fc);
		hiddenFCs = next;
		const vis = visible ? 'visible' : 'none';
		map.setLayoutProperty(fcFillId(fc), 'visibility', vis);
		map.setLayoutProperty(fcLineId(fc), 'visibility', vis);
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
		if (!fcListEl || !data) return;
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

	// ── Hover popup ──────────────────────────────────────────────────────────
	function setupHover() {
		if (!map || !data) return;
		const m = map;
		for (const fc of data.fc_names) {
			const fillId = `fc-fill-${fc}`;
			let hoveredId: number | null = null;
			m.on('mousemove', fillId, (e) => {
				if (!e.features?.length) return;
				const f = e.features[0]; const fid = f.id as number;
				if (hoveredId !== null && hoveredId !== fid)
					m.setFeatureState({ source: `fc-${fc}`, sourceLayer: fc, id: hoveredId }, { hover: false });
				hoveredId = fid;
				m.setFeatureState({ source: `fc-${fc}`, sourceLayer: fc, id: fid }, { hover: true });
				const record = data!.features[String(fid)];
				if (record) {
					if (!popup) popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '280px' });
					popup.setLngLat(e.lngLat).setHTML(renderPopupHtml(record, String(fid))).addTo(m);
				}
			});
			m.on('mouseleave', fillId, () => {
				if (hoveredId !== null) {
					m.setFeatureState({ source: `fc-${fc}`, sourceLayer: fc, id: hoveredId }, { hover: false });
					hoveredId = null;
				}
				popup?.remove(); popup = null;
			});
		}
	}

	function renderPopupHtml(record: { name: string; fc: string; [k: string]: unknown }, featureId: string): string {
		const lines: string[] = [
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
		if (!map || !data) return;
		const col = (activeColumn ?? 'map').replace(/^~/, '');
		const date = new Date().toISOString().slice(0, 10);
		void drawMapExport(map, {
			title: data.selection_label || data.request_name || '',
			columnLabel: activeColumn
				? activeColumn.startsWith('~') ? activeColumn.slice(1) : prettyColumn(activeColumn)
				: null,
			palette: PALETTES[currentPalette].colors,
			breaks: currentBreaks,
			stats,
			filename: `geoquery-${requestId.slice(0, 8)}-${col}-${date}.png`
		});
	}

	function fcFeatureCount(fc: string): number {
		if (!data) return 0;
		let count = 0;
		for (const feat of Object.values(data.features)) { if (feat.fc === fc) count++; }
		return count;
	}
</script>

<svelte:head>
	<title>Visualization · {data?.request_name ?? requestId.slice(0, 8)} · GeoQuery</title>
</svelte:head>

<div class="viz-page flex h-[calc(100vh-5rem)]">
	{#if loading}
		<div class="flex w-full items-center justify-center text-sm text-muted-foreground">
			Loading visualization…
		</div>
	{:else if loadError}
		<div class="flex w-full items-center justify-center gap-2 text-sm text-destructive">
			<AlertCircle class="size-4" aria-hidden="true" />{loadError}
		</div>
	{:else if data && data.request_status !== 1}
		<div class="mx-auto flex max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
			<AlertCircle class="size-6 text-warning-text" aria-hidden="true" />
			<p class="text-base font-bold">Request not yet complete</p>
			<p class="text-sm text-muted-foreground">Check back once it finishes.</p>
			<a href={`/requests/${requestId}`} class="text-sm text-link underline hover:text-link-hover">View request status →</a>
		</div>
	{:else if data && data.columns.length === 0}
		<div class="mx-auto flex max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
			<AlertCircle class="size-6 text-warning-text" aria-hidden="true" />
			<p class="text-base font-bold">No visualization data</p>
			<p class="text-sm text-muted-foreground">This request completed but no extract values were produced.</p>
		</div>
	{:else if data}
		<div class="flex flex-col flex-1 min-h-0">

		<!-- Top bar: request label + tab switcher -->
		<div class="flex items-center justify-between border-b px-4 py-2.5 shrink-0 bg-card gap-4">
			<div class="min-w-0">
				<p class="truncate text-sm font-bold">{data.selection_label || data.request_name}</p>
				<p class="text-xs text-muted-foreground">Request <span class="font-ui font-bold">{data.request_id.slice(0, 8)}…</span></p>
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

			<!-- Column picker (checkboxes) -->
			<div class="border-b px-4 py-3">
				<div class="panel-title">Data Columns</div>
				<p class="mb-2 text-xs text-muted-foreground">Check to include in popup · click name to set map layer</p>
				<div class="space-y-2">
					{#each Object.entries(data.col_groups) as [group, cols]}
						<div>
							<p class="mb-1 text-xs font-bold text-muted-foreground/70">{group}</p>
							{#each cols as col}
								<div class="col-row {activeColumn === col ? 'col-row-active' : ''}">
									<Checkbox
										checked={checkedColumns.has(col)}
										onCheckedChange={(checked) => setColumnChecked(col, checked)}
										aria-label="Include {prettyColumn(col)} in popup"
									/>
									<button
										class="col-name flex-1 text-left"
										onclick={() => { if (checkedColumns.has(col)) activeColumn = col; }}
										title={data.col_filter_desc?.[col] || data.col_descriptions[col] || col}
									>{prettyColumn(col)}</button>
									{#if activeColumn === col}
										<span class="active-badge">map</span>
									{/if}
								</div>
							{/each}
						</div>
					{/each}

					<!-- Custom indices -->
					{#each customIndices as ci}
						<div class="col-row {activeColumn === `~${ci.name}` ? 'col-row-active' : ''}">
							<Checkbox
								checked={checkedColumns.has(`~${ci.name}`)}
								onCheckedChange={(checked) => setColumnChecked(`~${ci.name}`, checked)}
								aria-label="Include {ci.name} in popup"
							/>
							<button
								class="col-name flex-1 text-left italic"
								onclick={() => { if (checkedColumns.has(`~${ci.name}`)) activeColumn = `~${ci.name}`; }}
								title={ci.formula}
							>{ci.name}</button>
							{#if activeColumn === `~${ci.name}`}
								<span class="active-badge">map</span>
							{/if}
							<Button
								variant="ghost"
								size="icon-sm"
								onclick={() => removeCustomIndex(ci.name)}
								class="size-6 text-muted-foreground hover:text-destructive"
								aria-label="Remove index {ci.name}"
							><X class="size-3.5" /></Button>
						</div>
					{/each}
				</div>

				<!-- Index builder toggle -->
				<Button
					variant="link"
					size="xs"
					class="mt-1 px-0"
					onclick={() => { showIndexBuilder = !showIndexBuilder; indexError = ''; }}
				>
					<Plus />
					{showIndexBuilder ? 'Cancel' : 'Add custom index'}
				</Button>

				{#if showIndexBuilder}
					<div class="mt-2 space-y-1.5 rounded-md bg-muted p-2">
						<Input
							type="text"
							placeholder="Index name"
							aria-label="Index name"
							bind:value={indexName}
							class="min-h-8"
						/>
						<textarea
							placeholder="Formula, e.g. [pop_count] / [land_area]"
							aria-label="Formula"
							bind:value={indexFormula}
							rows="2"
							class="formula-input"
						></textarea>
						<!-- Column insert chips -->
						<div class="flex flex-wrap gap-1">
							{#each data.columns as col}
								{@const meta = [data.col_dataset_titles[col], data.col_temporal[col]].filter(Boolean).join(' · ')}
								<button
									class="rounded-sm bg-card px-1.5 py-0.5 text-left text-muted-foreground hover:bg-accent hover:text-accent-foreground"
									onclick={() => insertColumn(col)}
								>
									{#if meta}<span class="block text-xs opacity-60">{meta}</span>{/if}
									<span class="block text-xs">{prettyColumn(col)}</span>
								</button>
							{/each}
						</div>
						{#if indexError}
							<p class="text-xs text-danger-text">{indexError}</p>
						{/if}
						<Button size="sm" onclick={addCustomIndex}>Add index</Button>
					</div>
				{/if}
			</div>

			<!-- Palette -->
			<div class="border-b px-4 py-3">
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

			<!-- Classification -->
			<div class="border-b px-4 py-3">
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

			<!-- Legend -->
			<div class="border-b px-4 py-3">
				<div class="panel-title">Legend</div>
				<MapLegend palette={PALETTES[currentPalette].colors} breaks={currentBreaks} />
			</div>

			<!-- Stats -->
			<div class="border-b px-4 py-3">
				<div class="panel-title">Statistics</div>
				<div class="stats-grid">
					<div><div class="stat-label">Min</div><div class="stat-value">{stats ? fmt(stats.min) : '—'}</div></div>
					<div><div class="stat-label">Max</div><div class="stat-value">{stats ? fmt(stats.max) : '—'}</div></div>
					<div><div class="stat-label">Mean</div><div class="stat-value">{stats ? fmt(stats.mean) : '—'}</div></div>
					<div><div class="stat-label">Features</div><div class="stat-value">{stats?.n ?? '—'}</div></div>
				</div>
			</div>

			<!-- FC list -->
			<div class="px-4 py-3">
				<div class="panel-title">Feature Collections</div>
				<div bind:this={fcListEl} class="space-y-0.5">
					{#each fcOrder as fc (fc)}
						<div class="fc-row" data-fc={fc}>
							<span class="fc-grip" aria-hidden="true"><GripVertical class="size-3.5" /></span>
							<Checkbox checked={!hiddenFCs.has(fc)}
								onCheckedChange={(checked) => toggleFC(fc, checked)}
								aria-label="Show {fc}" />
							<span class="fc-name" title={fc}>{fc}</span>
							<span class="fc-count">{fcFeatureCount(fc)}</span>
						</div>
					{/each}
				</div>
				<p class="mt-2 text-xs text-muted-foreground">Drag to reorder — top draws on top.</p>
			</div>
		</aside>
		{/if}

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
				{#if chartsVisited}
					<div class="absolute inset-0 z-10 bg-background" hidden={activeTab !== 'charts'}>
						{#await loadChartPanel() then { default: ChartPanel }}
							<ChartPanel {data} />
						{/await}
					</div>
				{/if}
		</div>
		</div>
		</div>
	{/if}
</div>

<style>
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

	.col-row {
		display: flex; align-items: center; gap: 6px;
		padding: 2px 4px; border-radius: 4px; font-size: var(--text-sm);
	}
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
