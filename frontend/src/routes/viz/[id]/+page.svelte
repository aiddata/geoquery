<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { page } from '$app/state';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { layers, namedFlavor } from '@protomaps/basemaps';
	import { fetchVisualizationData, fetchConfig, boundaryTileUrl, type VisualizationData } from '$lib/api';
	import {
		PALETTES, quantileBreaks, equalBreaks, buildColorExpression,
		fmt, prettyColumn, escapeHtml, computeStats,
	} from '$lib/viz';
	import { parseFormula, evaluateFormula, formulaColumns } from '$lib/formula';
	import { GripVertical, AlertCircle, Plus, X } from '@lucide/svelte';

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

	let currentPalette = $state<string>('YlOrRd');
	let currentMethod = $state<'quantile' | 'equal' | 'jenks'>('quantile');
	let currentBreaks = $state<number[] | null>(null);
	let hiddenFCs = $state<Set<string>>(new Set());
	let fcOrder = $state<string[]>([]);
	let stats = $state<{ min: number; max: number; mean: number; n: number } | null>(null);
	let popup: maplibregl.Popup | null = null;

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

	function insertColumn(col: string) {
		indexFormula += `[${col}]`;
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
		const config = await fetchConfig();
		map = new maplibregl.Map({
			container: mapContainer,
			style: {
				version: 8,
				glyphs: 'https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf',
				sprite: 'https://protomaps.github.io/basemaps-assets/sprites/v4/light',
				sources: {
					protomaps: {
						type: 'vector',
						tiles: [`https://api.protomaps.com/tiles/v4/{z}/{x}/{y}.mvt?key=${config.protomaps_api_key}`],
						maxzoom: 15,
						attribution: '<a href="https://protomaps.com">Protomaps</a> &copy; <a href="https://openstreetmap.org">OpenStreetMap</a>'
					}
				},
				layers: layers('protomaps', namedFlavor('light'), { lang: 'en' })
			},
			center: [0, 20],
			zoom: 2
		});

		map.on('load', () => {
			addFeatureLayers();
			setupHover();
			fitToBbox();
			mapReady = true;
			applyColors();
		});
	}

	function addFeatureLayers() {
		if (!map || !data) return;
		for (const fc of data.fc_names) {
			map.addSource(`fc-${fc}`, {
				type: 'vector',
				tiles: [boundaryTileUrl(fc)],
				minzoom: 0, maxzoom: 12,
				promoteId: { [fc]: 'id' }
			});
			map.addLayer({
				id: `fc-fill-${fc}`, type: 'fill',
				source: `fc-${fc}`, 'source-layer': fc,
				paint: {
					'fill-color': ['case', ['boolean', ['feature-state', 'hover'], false], '#fff', '#cbd5e1'],
					'fill-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.9, 0.75]
				}
			});
			map.addLayer({
				id: `fc-line-${fc}`, type: 'line',
				source: `fc-${fc}`, 'source-layer': fc,
				paint: { 'line-color': '#334155', 'line-width': 0.75 }
			});
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
				map.setPaintProperty(`fc-fill-${fc}`, 'fill-color', '#cbd5e1');
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

	function toggleFC(fc: string, visible: boolean) {
		if (!map) return;
		const next = new Set(hiddenFCs);
		if (visible) next.delete(fc); else next.add(fc);
		hiddenFCs = next;
		const vis = visible ? 'visible' : 'none';
		map.setLayoutProperty(`fc-fill-${fc}`, 'visibility', vis);
		map.setLayoutProperty(`fc-line-${fc}`, 'visibility', vis);
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
		if (!fcListEl || !data) return;
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

	onMount(() => () => { map?.remove(); map = null; popup?.remove(); popup = null; sortable?.destroy(); });

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
			<AlertCircle class="h-4 w-4" />{loadError}
		</div>
	{:else if data && data.request_status !== 1}
		<div class="mx-auto flex max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
			<AlertCircle class="h-6 w-6 text-amber-500" />
			<p class="text-base font-semibold">Request not yet complete</p>
			<p class="text-sm text-muted-foreground">Check back once it finishes.</p>
			<a href={`/requests/${requestId}`} class="text-sm text-primary underline hover:no-underline">View request status →</a>
		</div>
	{:else if data && data.columns.length === 0}
		<div class="mx-auto flex max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
			<AlertCircle class="h-6 w-6 text-amber-500" />
			<p class="text-base font-semibold">No visualization data</p>
			<p class="text-sm text-muted-foreground">This request completed but no extract values were produced.</p>
		</div>
	{:else if data}
		<aside class="w-72 shrink-0 overflow-y-auto border-r bg-card">
			<!-- Header -->
			<div class="border-b px-4 py-3">
				<p class="truncate text-sm font-semibold">{data.selection_label || data.request_name}</p>
				<p class="mt-0.5 font-mono text-[10px] text-muted-foreground">Request {data.request_id.slice(0, 8)}…</p>
			</div>

			<!-- Column picker (checkboxes) -->
			<div class="border-b px-4 py-3">
				<div class="panel-title">Data Columns</div>
				<p class="mb-2 text-[10px] text-muted-foreground">Check to include in popup · click name to set map layer</p>
				<div class="space-y-2">
					{#each Object.entries(data.col_groups) as [group, cols]}
						<div>
							<p class="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">{group}</p>
							{#each cols as col}
								<label class="col-row {activeColumn === col ? 'col-row-active' : ''}">
									<input
										type="checkbox"
										checked={checkedColumns.has(col)}
										onchange={(e) => {
											const next = new Set(checkedColumns);
											if ((e.target as HTMLInputElement).checked) {
												next.add(col);
												activeColumn = col;
											} else {
												next.delete(col);
												if (activeColumn === col) activeColumn = [...next][0] ?? null;
											}
											checkedColumns = next;
										}}
									/>
									<button
										class="col-name flex-1 text-left"
										onclick={() => { if (checkedColumns.has(col)) activeColumn = col; }}
										title={data.col_descriptions[col] || col}
									>{prettyColumn(col)}</button>
									{#if activeColumn === col}
										<span class="active-badge">map</span>
									{/if}
								</label>
							{/each}
						</div>
					{/each}

					<!-- Custom indices -->
					{#each customIndices as ci}
						<label class="col-row {activeColumn === `~${ci.name}` ? 'col-row-active' : ''}">
							<input
								type="checkbox"
								checked={checkedColumns.has(`~${ci.name}`)}
								onchange={(e) => {
									const key = `~${ci.name}`;
									const next = new Set(checkedColumns);
									if ((e.target as HTMLInputElement).checked) {
										next.add(key); activeColumn = key;
									} else {
										next.delete(key);
										if (activeColumn === key) activeColumn = [...next][0] ?? null;
									}
									checkedColumns = next;
								}}
							/>
							<button
								class="col-name flex-1 text-left italic"
								onclick={() => { if (checkedColumns.has(`~${ci.name}`)) activeColumn = `~${ci.name}`; }}
								title={ci.formula}
							>{ci.name}</button>
							{#if activeColumn === `~${ci.name}`}
								<span class="active-badge">map</span>
							{/if}
							<button
								onclick={() => removeCustomIndex(ci.name)}
								class="ml-1 text-muted-foreground hover:text-destructive"
								title="Remove index"
							><X class="h-3 w-3" /></button>
						</label>
					{/each}
				</div>

				<!-- Index builder toggle -->
				<button
					class="mt-2 flex items-center gap-1 text-[11px] text-primary hover:underline"
					onclick={() => { showIndexBuilder = !showIndexBuilder; indexError = ''; }}
				>
					<Plus class="h-3 w-3" />
					{showIndexBuilder ? 'Cancel' : 'Add custom index'}
				</button>

				{#if showIndexBuilder}
					<div class="mt-2 space-y-1.5 rounded-md border bg-muted/30 p-2">
						<input
							type="text"
							placeholder="Index name"
							bind:value={indexName}
							class="viz-input"
						/>
						<textarea
							placeholder="Formula, e.g. [pop_count] / [land_area]"
							bind:value={indexFormula}
							rows="2"
							class="viz-input resize-none font-mono text-[11px]"
						></textarea>
						<!-- Column insert chips -->
						<div class="flex flex-wrap gap-1">
							{#each data.columns as col}
								{@const meta = [data.col_dataset_titles[col], data.col_temporal[col]].filter(Boolean).join(' · ')}
								<button
									class="rounded bg-muted px-1.5 py-0.5 text-left text-muted-foreground hover:bg-accent"
									onclick={() => insertColumn(col)}
								>
									{#if meta}<span class="block text-[9px] opacity-60">{meta}</span>{/if}
									<span class="block text-[10px]">{prettyColumn(col)}</span>
								</button>
							{/each}
						</div>
						{#if indexError}
							<p class="text-[11px] text-destructive">{indexError}</p>
						{/if}
						<button class="viz-btn-primary" onclick={addCustomIndex}>Add index</button>
					</div>
				{/if}
			</div>

			<!-- Palette -->
			<div class="border-b px-4 py-3">
				<div class="panel-title">Color Palette</div>
				<select bind:value={currentPalette} class="viz-select">
					{#each Object.entries(PALETTES) as [key, p]}
						<option value={key}>{p.label}</option>
					{/each}
				</select>
			</div>

			<!-- Classification -->
			<div class="border-b px-4 py-3">
				<div class="panel-title">Classification</div>
				<select bind:value={currentMethod} class="viz-select">
					<option value="quantile">Quantile</option>
					<option value="equal">Equal interval</option>
					<option value="jenks">Natural Breaks (Jenks)</option>
				</select>
			</div>

			<!-- Legend -->
			<div class="border-b px-4 py-3">
				<div class="panel-title">Legend</div>
				{#if currentBreaks}
					{@const palette = PALETTES[currentPalette].colors}
					<div class="space-y-1">
						{#each palette as color, i}
							<div class="legend-item">
								<span class="legend-swatch" style="background: {color}"></span>
								<span>{fmt(currentBreaks[i])} – {fmt(currentBreaks[i + 1])}</span>
							</div>
						{/each}
						<div class="legend-item legend-nodata">
							<span class="legend-swatch" style="background: #cbd5e1"></span>
							<span>No data</span>
						</div>
					</div>
				{:else}
					<p class="text-[11px] text-muted-foreground">No numeric data for this column.</p>
				{/if}
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
							<span class="fc-grip"><GripVertical class="h-3.5 w-3.5" /></span>
							<input type="checkbox" checked={!hiddenFCs.has(fc)}
								onchange={(e) => toggleFC(fc, (e.target as HTMLInputElement).checked)} />
							<span class="fc-name" title={fc}>{fc}</span>
							<span class="fc-count">{fcFeatureCount(fc)}</span>
						</div>
					{/each}
				</div>
				<p class="mt-2 text-[10px] text-muted-foreground">Drag to reorder — top draws on top.</p>
			</div>
		</aside>

		<div class="relative flex-1">
			<div bind:this={mapContainer} class="h-full w-full"></div>
		</div>
	{/if}
</div>

<style>
	.panel-title {
		font-size: 10px; font-weight: 600; text-transform: uppercase;
		letter-spacing: 0.07em; color: #94a3b8; margin-bottom: 6px;
	}
	.viz-select {
		width: 100%; padding: 5px 8px; border: 1px solid #e2e8f0;
		border-radius: 6px; font-size: 12px; background: #fff; color: #1e293b; cursor: pointer;
	}
	.viz-select:focus { outline: 2px solid #3b82f6; outline-offset: -1px; }
	.viz-input {
		width: 100%; padding: 4px 7px; border: 1px solid #e2e8f0;
		border-radius: 5px; font-size: 12px; background: #fff; color: #1e293b;
	}
	.viz-input:focus { outline: 2px solid #3b82f6; outline-offset: -1px; }
	.viz-btn-primary {
		padding: 4px 10px; background: #3b82f6; color: #fff;
		border-radius: 5px; font-size: 12px; font-weight: 500;
	}
	.viz-btn-primary:hover { background: #2563eb; }

	.col-row {
		display: flex; align-items: center; gap: 5px;
		padding: 2px 4px; border-radius: 4px; font-size: 12px; cursor: pointer;
	}
	.col-row:hover { background: #f8fafc; }
	.col-row-active { background: #eff6ff; }
	.col-row input[type="checkbox"] { flex-shrink: 0; accent-color: #3b82f6; cursor: pointer; }
	.col-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #1e293b; background: none; border: none; padding: 0; font-size: inherit; cursor: pointer; }
	.active-badge { font-size: 9px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: #2563eb; background: #dbeafe; border-radius: 3px; padding: 1px 5px; flex-shrink: 0; line-height: 1.4; }

	.stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
	.stat-label { font-size: 9px; text-transform: uppercase; letter-spacing: 0.06em; color: #94a3b8; }
	.stat-value { font-size: 13px; font-weight: 500; color: #1e293b; font-variant-numeric: tabular-nums; }

	.legend-item { display: flex; align-items: center; gap: 8px; font-size: 11px; color: #475569; font-variant-numeric: tabular-nums; }
	.legend-item.legend-nodata { opacity: 0.55; }
	.legend-swatch { width: 13px; height: 13px; border-radius: 2px; flex-shrink: 0; border: 1px solid rgba(0,0,0,0.08); }

	.fc-row { display: flex; align-items: center; gap: 6px; padding: 3px 2px; border-radius: 4px; font-size: 12px; cursor: grab; user-select: none; }
	.fc-row:active { cursor: grabbing; }
	.fc-row:hover { background: #f8fafc; }
	.fc-row input[type="checkbox"] { flex-shrink: 0; cursor: pointer; accent-color: #3b82f6; }
	.fc-row .fc-grip { flex-shrink: 0; color: #cbd5e1; display: inline-flex; }
	.fc-row .fc-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
	.fc-row .fc-count { font-size: 10px; color: #94a3b8; flex-shrink: 0; }

	:global(.fc-row-ghost) { opacity: 0.4; background: #eff6ff; }
	:global(.fc-row-chosen) { background: #f1f5f9; }

	:global(.maplibregl-popup-content) { font-size: 12px; padding: 8px 10px; border-radius: 6px; }
	:global(.popup-name) { font-weight: 600; color: #0f172a; }
	:global(.popup-fc) { font-size: 10px; color: #94a3b8; margin-bottom: 4px; }
	:global(.popup-row) { display: flex; gap: 8px; justify-content: space-between; margin-top: 2px; }
	:global(.popup-row-active) { font-weight: 500; }
	:global(.popup-col) { color: #64748b; }
	:global(.popup-val) { font-weight: 500; color: #1e293b; font-variant-numeric: tabular-nums; }
	:global(.popup-desc) { font-size: 10px; color: #94a3b8; margin-top: 2px; }
</style>
