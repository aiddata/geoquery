<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { page } from '$app/state';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { layers, namedFlavor } from '@protomaps/basemaps';
	import { fetchVisualizationData, fetchConfig, boundaryTileUrl, type VisualizationData } from '$lib/api';
	import { GripVertical, AlertCircle } from '@lucide/svelte';

	const requestId = page.params.id;

	// ── State ────────────────────────────────────────────────────────────────
	let data = $state<VisualizationData | null>(null);
	let loading = $state(true);
	let loadError = $state('');

	let mapContainer: HTMLDivElement;
	let map: maplibregl.Map | null = $state(null);
	let mapReady = $state(false);

	let currentColumn = $state<string | null>(null);
	let currentPalette = $state<string>('YlOrRd');
	let currentMethod = $state<'quantile' | 'equal' | 'jenks'>('quantile');

	// Active break thresholds for the current view — drives the legend
	let currentBreaks = $state<number[] | null>(null);

	// Visibility + order. Top of list = drawn on top of the map.
	let hiddenFCs = $state<Set<string>>(new Set());
	let fcOrder = $state<string[]>([]);

	// Stats for the current column
	let stats = $state<{ min: number; max: number; mean: number; n: number } | null>(null);

	// Hover popup
	let popup: maplibregl.Popup | null = null;

	// ── Palettes (5-class ColorBrewer) ───────────────────────────────────────
	const PALETTES: Record<string, { label: string; colors: string[] }> = {
		YlOrRd:  { label: 'Yellow → Orange → Red',  colors: ['#ffffb2','#fecc5c','#fd8d3c','#f03b20','#bd0026'] },
		Blues:   { label: 'Blues',                   colors: ['#eff3ff','#bdd7e7','#6baed6','#3182bd','#08519c'] },
		Greens:  { label: 'Greens',                  colors: ['#edf8e9','#bae4b3','#74c476','#31a354','#006d2c'] },
		Purples: { label: 'Purples',                 colors: ['#f2f0f7','#cbc9e2','#9e9ac8','#756bb1','#54278f'] },
		Oranges: { label: 'Oranges',                 colors: ['#feedde','#fdbe85','#fd8d3c','#e6550d','#a63603'] },
		YlGn:    { label: 'Yellow → Green',          colors: ['#ffffcc','#c2e699','#78c679','#31a354','#006837'] },
		RdYlGn:  { label: 'Red → Yellow → Green ↔', colors: ['#d7191c','#fdae61','#ffffbf','#a6d96a','#1a9641'] },
		RdBu:    { label: 'Red → Blue ↔',           colors: ['#ca0020','#f4a582','#f7f7f7','#92c5de','#0571b0'] },
		PuOr:    { label: 'Purple → Orange ↔',      colors: ['#5e3696','#b2abd2','#f7f7f7','#fdb863','#e66101'] },
		BrBG:    { label: 'Brown → Blue-Green ↔',   colors: ['#8c510a','#d8b365','#f5f5f5','#5ab4ac','#01665e'] }
	};

	// ── Data load ────────────────────────────────────────────────────────────
	onMount(async () => {
		try {
			const result = await fetchVisualizationData(requestId);
			data = result;
			currentColumn = result.columns[0] ?? null;
			// Top of list = drawn on top, so reverse the API order
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
				tiles: [`${window.location.origin}/api/features/tiles/${fc}/{z}/{x}/{y}.mvt`],
				minzoom: 0,
				maxzoom: 12,
				promoteId: { [fc]: 'id' }
			});

			map.addLayer({
				id: `fc-fill-${fc}`,
				type: 'fill',
				source: `fc-${fc}`,
				'source-layer': fc,
				paint: {
					'fill-color': ['case',
						['boolean', ['feature-state', 'hover'], false], '#fff',
						'#cbd5e1'
					],
					'fill-opacity': ['case',
						['boolean', ['feature-state', 'hover'], false], 0.9,
						0.75
					]
				}
			});

			map.addLayer({
				id: `fc-line-${fc}`,
				type: 'line',
				source: `fc-${fc}`,
				'source-layer': fc,
				paint: { 'line-color': '#334155', 'line-width': 0.75 }
			});
		}
	}

	function fitToBbox() {
		if (!map || !data?.bbox) return;
		const [w, s, e, n] = data.bbox;
		map.fitBounds([[w, s], [e, n]], { padding: 40, maxZoom: 10, duration: 0 });
	}

	// ── Classification + coloring ────────────────────────────────────────────
	function quantileBreaks(values: number[], n: number): number[] {
		const sorted = [...values].sort((a, b) => a - b);
		if (sorted[0] === sorted[sorted.length - 1]) {
			return Array.from({ length: n + 1 }, () => sorted[0]);
		}
		const breaks = [sorted[0]];
		for (let i = 1; i <= n; i++) {
			breaks.push(sorted[Math.round((i / n) * (sorted.length - 1))]);
		}
		return breaks;
	}

	function equalBreaks(values: number[], n: number): number[] {
		const min = Math.min(...values), max = Math.max(...values);
		const step = (max - min) / n;
		return Array.from({ length: n + 1 }, (_, i) => min + i * step);
	}

	function getColor(value: unknown, breaks: number[], palette: string[]): string {
		if (value === null || value === undefined || isNaN(Number(value))) return '#cbd5e1';
		const v = Number(value);
		for (let i = 1; i < breaks.length; i++) {
			if (v <= breaks[i]) return palette[i - 1];
		}
		return palette[palette.length - 1];
	}

	function buildColorExpression(fc: string, column: string, breaks: number[], palette: string[]) {
		const expr: unknown[] = ['match', ['get', 'id']];
		for (const [idStr, feat] of Object.entries(data!.features)) {
			if (feat.fc !== fc) continue;
			expr.push(parseInt(idStr), getColor(feat[column], breaks, palette));
		}
		expr.push('#cbd5e1');
		return expr;
	}

	async function applyColors() {
		if (!map || !mapReady || !data || !currentColumn) return;

		// Gather numeric values for the current column across all visible features
		const values: number[] = [];
		for (const feat of Object.values(data.features)) {
			if (hiddenFCs.has(feat.fc)) continue;
			const v = feat[currentColumn];
			if (v !== null && v !== undefined && !isNaN(Number(v))) values.push(Number(v));
		}

		if (values.length === 0) {
			stats = null;
			currentBreaks = null;
			// Reset to neutral fill
			for (const fc of data.fc_names) {
				map.setPaintProperty(`fc-fill-${fc}`, 'fill-color', '#cbd5e1');
			}
			return;
		}

		let breaks: number[];
		if (currentMethod === 'quantile') {
			breaks = quantileBreaks(values, 5);
		} else if (currentMethod === 'equal') {
			breaks = equalBreaks(values, 5);
		} else {
			// Jenks via simple-statistics — code-split since it's only used here
			const ss = await import('simple-statistics');
			breaks = ss.jenks(values, 5) as number[];
		}
		const palette = PALETTES[currentPalette].colors;

		for (const fc of data.fc_names) {
			const expr = buildColorExpression(fc, currentColumn, breaks, palette);
			// Hover treatment: white fill, otherwise the choropleth expression
			map.setPaintProperty(`fc-fill-${fc}`, 'fill-color', [
				'case',
				['boolean', ['feature-state', 'hover'], false], '#fff',
				expr
			]);
		}

		currentBreaks = breaks;
		const min = Math.min(...values), max = Math.max(...values);
		const mean = values.reduce((a, b) => a + b, 0) / values.length;
		stats = { min, max, mean, n: values.length };
	}

	// React to control changes
	$effect(() => {
		void currentColumn; void currentPalette; void currentMethod; void hiddenFCs;
		if (mapReady) applyColors();
	});

	// ── Visibility toggle ────────────────────────────────────────────────────
	function toggleFC(fc: string, visible: boolean) {
		if (!map) return;
		const next = new Set(hiddenFCs);
		if (visible) next.delete(fc); else next.add(fc);
		hiddenFCs = next;
		const vis = visible ? 'visible' : 'none';
		map.setLayoutProperty(`fc-fill-${fc}`, 'visibility', vis);
		map.setLayoutProperty(`fc-line-${fc}`, 'visibility', vis);
	}

	// ── Layer order — driven by fcOrder; reapplied to map on change ──────────
	$effect(() => {
		if (!mapReady || !map) return;
		const m = map;
		const order = fcOrder;
		// Walk reverse so the last-moved is on top
		for (let i = order.length - 1; i >= 0; i--) {
			const fc = order[i];
			if (m.getLayer(`fc-fill-${fc}`)) m.moveLayer(`fc-fill-${fc}`);
			if (m.getLayer(`fc-line-${fc}`)) m.moveLayer(`fc-line-${fc}`);
		}
	});

	// ── Drag-to-reorder via SortableJS (loaded on demand) ────────────────────
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
				animation: 150,
				filter: 'input[type="checkbox"]',
				preventOnFilter: false,
				ghostClass: 'fc-row-ghost',
				chosenClass: 'fc-row-chosen',
				onEnd: () => {
					if (!fcListEl) return;
					const newOrder = Array.from(fcListEl.children)
						.map((el) => (el as HTMLElement).dataset.fc)
						.filter((v): v is string => !!v);
					fcOrder = newOrder;
				}
			});
		})();
		return () => {
			cancelled = true;
			sortable?.destroy();
			sortable = null;
		};
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
				const f = e.features[0];
				const fid = f.id as number;
				if (hoveredId !== null && hoveredId !== fid) {
					m.setFeatureState({ source: `fc-${fc}`, sourceLayer: fc, id: hoveredId }, { hover: false });
				}
				hoveredId = fid;
				m.setFeatureState({ source: `fc-${fc}`, sourceLayer: fc, id: fid }, { hover: true });

				const record = data!.features[String(fid)];
				if (record) {
					const html = renderPopupHtml(record);
					if (!popup) popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '280px' });
					popup.setLngLat(e.lngLat).setHTML(html).addTo(m);
				}
			});

			m.on('mouseleave', fillId, () => {
				if (hoveredId !== null) {
					m.setFeatureState({ source: `fc-${fc}`, sourceLayer: fc, id: hoveredId }, { hover: false });
					hoveredId = null;
				}
				popup?.remove();
				popup = null;
			});
		}
	}

	function renderPopupHtml(record: { name: string; fc: string; [k: string]: unknown }): string {
		const lines: string[] = [`<div class="popup-name">${escapeHtml(record.name)}</div>`];
		lines.push(`<div class="popup-fc">${escapeHtml(record.fc)}</div>`);
		if (currentColumn !== null) {
			const val = record[currentColumn];
			const valStr = (val === null || val === undefined) ? '—' : String(val);
			const desc = data?.col_descriptions[currentColumn];
			lines.push(`<div class="popup-row"><span class="popup-col">${escapeHtml(prettyColumn(currentColumn))}</span><span class="popup-val">${escapeHtml(valStr)}</span></div>`);
			if (desc) lines.push(`<div class="popup-desc">${escapeHtml(desc)}</div>`);
		}
		return lines.join('');
	}

	function prettyColumn(col: string): string {
		const parts = col.split('.');
		return parts.length > 1 ? parts.slice(1).join('.') : col;
	}

	function escapeHtml(s: string): string {
		return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
	}

	// ── Cleanup ──────────────────────────────────────────────────────────────
	onMount(() => () => {
		map?.remove();
		map = null;
		popup?.remove();
		popup = null;
		sortable?.destroy();
	});

	// ── Display helpers ──────────────────────────────────────────────────────
	function fmt(n: number | null | undefined): string {
		if (n === null || n === undefined || !isFinite(n)) return '—';
		const abs = Math.abs(n);
		if (abs >= 10000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
		if (abs >= 100) return n.toFixed(1);
		if (abs >= 1) return n.toFixed(3);
		if (n === 0) return '0';
		return n.toPrecision(3);
	}

	function fcFeatureCount(fc: string): number {
		if (!data) return 0;
		let count = 0;
		for (const feat of Object.values(data.features)) {
			if (feat.fc === fc) count++;
		}
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
			<AlertCircle class="h-4 w-4" />
			{loadError}
		</div>
	{:else if data}
		<!-- Sidebar -->
		<aside class="w-72 shrink-0 overflow-y-auto border-r bg-card">
			<div class="border-b px-4 py-3">
				<p class="text-sm font-semibold text-foreground truncate">
					{data.selection_label || data.request_name}
				</p>
				<p class="mt-0.5 font-mono text-[10px] text-muted-foreground">
					Request {data.request_id.slice(0, 8)}…
				</p>
			</div>

			<!-- Column picker -->
			<div class="border-b px-4 py-3">
				<div class="panel-title">Data Column</div>
				<select bind:value={currentColumn} class="viz-select">
					{#each Object.entries(data.col_groups) as [group, cols]}
						<optgroup label={group}>
							{#each cols as col}
								<option value={col}>{prettyColumn(col)}</option>
							{/each}
						</optgroup>
					{/each}
				</select>
				{#if currentColumn && data.col_descriptions[currentColumn]}
					<p class="mt-1.5 text-[11px] text-muted-foreground">{data.col_descriptions[currentColumn]}</p>
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

			<!-- FC list with drag reorder -->
			<div class="px-4 py-3">
				<div class="panel-title">Feature Collections</div>
				<div bind:this={fcListEl} class="space-y-0.5">
					{#each fcOrder as fc (fc)}
						<div class="fc-row" data-fc={fc}>
							<span class="fc-grip" aria-hidden="true">
								<GripVertical class="h-3.5 w-3.5" />
							</span>
							<input
								type="checkbox"
								checked={!hiddenFCs.has(fc)}
								onchange={(e) => toggleFC(fc, (e.target as HTMLInputElement).checked)}
							/>
							<span class="fc-name" title={fc}>{fc}</span>
							<span class="fc-count">{fcFeatureCount(fc)}</span>
						</div>
					{/each}
				</div>
				<p class="mt-2 text-[10px] text-muted-foreground">
					Drag to reorder — top of list draws on top of the map.
				</p>
			</div>
		</aside>

		<!-- Map -->
		<div class="relative flex-1">
			<div bind:this={mapContainer} class="h-full w-full"></div>
		</div>
	{/if}
</div>

<style>
	.panel-title {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: #94a3b8;
		margin-bottom: 6px;
	}

	.viz-select {
		width: 100%;
		padding: 5px 8px;
		border: 1px solid #e2e8f0;
		border-radius: 6px;
		font-size: 12px;
		background: #fff;
		color: #1e293b;
		cursor: pointer;
	}
	.viz-select:focus { outline: 2px solid #3b82f6; outline-offset: -1px; }

	.stats-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 6px;
	}
	.stat-label {
		font-size: 9px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #94a3b8;
	}
	.stat-value {
		font-size: 13px;
		font-weight: 500;
		color: #1e293b;
		font-variant-numeric: tabular-nums;
	}

	.legend-item {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 11px;
		color: #475569;
		font-variant-numeric: tabular-nums;
	}
	.legend-item.legend-nodata { opacity: 0.55; }
	.legend-swatch {
		width: 13px;
		height: 13px;
		border-radius: 2px;
		flex-shrink: 0;
		border: 1px solid rgba(0, 0, 0, 0.08);
	}

	.fc-row {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 3px 2px;
		border-radius: 4px;
		font-size: 12px;
		cursor: grab;
		user-select: none;
	}
	.fc-row:active { cursor: grabbing; }
	.fc-row:hover { background: #f8fafc; }
	.fc-row input[type="checkbox"] { flex-shrink: 0; cursor: pointer; accent-color: #3b82f6; }
	.fc-row .fc-grip { flex-shrink: 0; color: #cbd5e1; display: inline-flex; }
	.fc-row .fc-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
	.fc-row .fc-count { font-size: 10px; color: #94a3b8; flex-shrink: 0; }

	:global(.fc-row-ghost) { opacity: 0.4; background: #eff6ff; }
	:global(.fc-row-chosen) { background: #f1f5f9; }

	:global(.maplibregl-popup-content) {
		font-size: 12px;
		padding: 8px 10px;
		border-radius: 6px;
	}
	:global(.popup-name) { font-weight: 600; color: #0f172a; }
	:global(.popup-fc) { font-size: 10px; color: #94a3b8; margin-bottom: 4px; }
	:global(.popup-row) { display: flex; gap: 8px; justify-content: space-between; margin-top: 2px; }
	:global(.popup-col) { color: #64748b; }
	:global(.popup-val) { font-weight: 500; color: #1e293b; font-variant-numeric: tabular-nums; }
	:global(.popup-desc) { font-size: 10px; color: #94a3b8; margin-top: 2px; }
</style>
