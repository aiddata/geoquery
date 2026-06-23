<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import { fmt, prettyColumn } from '$lib/viz';
	import { X, Plus, Download } from '@lucide/svelte';

	interface Props {
		data: VizPayload;
	}
	let { data }: Props = $props();

	interface ChartCard {
		id: string;
		type: 'histogram' | 'top_bar' | 'bottom_bar';
		column: string;
	}

	const CHART_TYPES: { value: ChartCard['type']; label: string }[] = [
		{ value: 'histogram', label: 'Distribution' },
		{ value: 'top_bar', label: 'Top Values' },
		{ value: 'bottom_bar', label: 'Bottom Values' },
	];

	const N_BINS = 20;
	const TOP_N = 15;

	let chartCards = $state<ChartCard[]>([]);
	let showAddPicker = $state(false);
	let newCardCol = $state('');
	let newCardType = $state<ChartCard['type']>('histogram');

	// Re-initialize when the set of columns changes (e.g. explore page loads new data).
	let columnsKey = $derived(data.columns.join('\x00'));
	let _lastKey = '';
	$effect(() => {
		const key = columnsKey;
		if (key === _lastKey) return;
		_lastKey = key;
		if (!data.columns.length) { chartCards = []; return; }
		newCardCol = data.columns[0];
		chartCards = [
			{ id: crypto.randomUUID(), type: 'histogram', column: data.columns[0] },
			{ id: crypto.randomUUID(), type: 'top_bar', column: data.columns[0] },
		];
	});

	function removeCard(id: string) {
		chartCards = chartCards.filter((c) => c.id !== id);
	}

	function updateCard(id: string, patch: Partial<Omit<ChartCard, 'id'>>) {
		chartCards = chartCards.map((c) => (c.id === id ? { ...c, ...patch } : c));
	}

	function addCard() {
		if (!newCardCol) return;
		chartCards = [...chartCards, { id: crypto.randomUUID(), type: newCardType, column: newCardCol }];
		showAddPicker = false;
	}

	const svgRefs = new Map<string, SVGSVGElement>();

	function registerSvg(node: SVGSVGElement, initialId: string) {
		let id = initialId;
		svgRefs.set(id, node);
		return {
			update(newId: string) { svgRefs.delete(id); svgRefs.set(newId, node); id = newId; },
			destroy() { svgRefs.delete(id); }
		};
	}

	function truncate(s: string, n: number): string {
		return s.length > n ? s.slice(0, n - 1) + '…' : s;
	}

	function exportCard(card: ChartCard) {
		const svg = svgRefs.get(card.id);
		if (!svg) return;
		const vb = svg.viewBox.baseVal;
		const scale = 2;
		const xml = new XMLSerializer().serializeToString(svg);
		const svgBlob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' });
		const url = URL.createObjectURL(svgBlob);
		const img = new Image();
		img.onload = () => {
			const pad = 24;
			const canvas = document.createElement('canvas');
			canvas.width = vb.width * scale + pad * 2;
			canvas.height = vb.height * scale + pad * 2;
			const ctx = canvas.getContext('2d')!;
			ctx.fillStyle = '#ffffff';
			ctx.fillRect(0, 0, canvas.width, canvas.height);
			ctx.drawImage(img, pad, pad, vb.width * scale, vb.height * scale);
			URL.revokeObjectURL(url);
			canvas.toBlob((b) => {
				if (!b) return;
				const pngUrl = URL.createObjectURL(b);
				const a = document.createElement('a');
				a.href = pngUrl;
				a.download = `${card.column}_${card.type}.png`;
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
				URL.revokeObjectURL(pngUrl);
			}, 'image/png');
		};
		img.src = url;
	}

	function getValues(col: string): number[] {
		const out: number[] = [];
		for (const f of Object.values(data.features)) {
			const v = f[col];
			if (v !== null && v !== undefined) {
				const n = Number(v);
				if (!isNaN(n)) out.push(n);
			}
		}
		return out;
	}

	interface Bin { lo: number; hi: number; count: number; }

	function makeBins(vals: number[]): Bin[] {
		if (!vals.length) return [];
		let min = vals[0], max = vals[0];
		for (const v of vals) { if (v < min) min = v; if (v > max) max = v; }
		if (min === max) return [{ lo: min, hi: max, count: vals.length }];
		const w = (max - min) / N_BINS;
		const bins: Bin[] = Array.from({ length: N_BINS }, (_, i) => ({
			lo: min + i * w, hi: min + (i + 1) * w, count: 0
		}));
		for (const v of vals) {
			const i = Math.min(Math.floor((v - min) / w), N_BINS - 1);
			bins[i].count++;
		}
		return bins;
	}

	function getRanked(col: string, dir: 'top' | 'bottom') {
		const rows: { name: string; v: number }[] = [];
		for (const f of Object.values(data.features)) {
			const v = Number(f[col]);
			if (!isNaN(v)) rows.push({ name: f.name, v });
		}
		rows.sort((a, b) => dir === 'top' ? b.v - a.v : a.v - b.v);
		return rows.slice(0, TOP_N);
	}

	function niceName(col: string): string {
		return prettyColumn(col).replace(/_/g, ' ');
	}

	function colLabel(col: string): string {
		const parts = [niceName(col), data.col_temporal[col]].filter(Boolean);
		return parts.join(' · ');
	}

	function cardTitle(card: ChartCard): { ds: string; col: string } {
		const ds = data.col_dataset_titles[card.column] ?? '';
		const typeLabel = CHART_TYPES.find(t => t.value === card.type)?.label ?? '';
		const temporal = data.col_temporal[card.column];
		const colPart = [niceName(card.column), temporal].filter(Boolean).join(' · ');
		return { ds: ds || niceName(card.column), col: `${colPart} — ${typeLabel}` };
	}

	function meanOf(vals: number[]): number {
		return vals.reduce((a, b) => a + b, 0) / vals.length;
	}
</script>

<div class="h-full overflow-y-auto">
	<div class="p-4 space-y-4">
		{#if chartCards.length === 0 && data.columns.length === 0}
			<div class="flex h-48 items-center justify-center text-sm text-muted-foreground">
				No data available.
			</div>
		{:else}
			<div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
				{#each chartCards as card (card.id)}
					{@const vals = getValues(card.column)}
					{@const dsTitle = data.col_dataset_titles[card.column] ?? ''}
					{@const temporal = data.col_temporal[card.column] ?? ''}
					{@const meta = [dsTitle, temporal].filter(Boolean).join(' · ')}

					<div class="rounded-lg border bg-card shadow-sm overflow-hidden">
						<!-- Card header -->
						<div class="flex items-center gap-2 px-3 py-2 border-b bg-muted/30">
							<select
								value={card.column}
								onchange={(e) => updateCard(card.id, { column: (e.target as HTMLSelectElement).value })}
								class="chart-select flex-1 min-w-0"
							>
								{#each Object.entries(data.col_groups) as [group, cols]}
									<optgroup label={group}>
										{#each cols as col}
											<option value={col}>{colLabel(col)}</option>
										{/each}
									</optgroup>
								{/each}
							</select>
							<select
								value={card.type}
								onchange={(e) => updateCard(card.id, { type: (e.target as HTMLSelectElement).value as ChartCard['type'] })}
								class="chart-select shrink-0"
								style="width: auto"
							>
								{#each CHART_TYPES as ct}
									<option value={ct.value}>{ct.label}</option>
								{/each}
							</select>
							<button
								onclick={() => exportCard(card)}
								class="shrink-0 text-muted-foreground hover:text-foreground"
								title="Save as PNG"
							>
								<Download class="h-3.5 w-3.5" />
							</button>
							<button
								onclick={() => removeCard(card.id)}
								class="shrink-0 text-muted-foreground hover:text-destructive"
								title="Remove chart"
							>
								<X class="h-3.5 w-3.5" />
							</button>
						</div>

						<!-- Chart body -->
						<div class="p-3">
							{#if vals.length === 0}
								<p class="text-center text-sm text-muted-foreground py-10">No numeric data for this column.</p>
							{:else if card.type === 'histogram'}
								{@const bins = makeBins(vals)}
								{@const maxCount = bins.reduce((a, b) => Math.max(a, b.count), 0)}
								{@const minVal = bins[0].lo}
								{@const maxVal = bins[bins.length - 1].hi}
								{@const rangeVal = maxVal - minVal}
								{@const m = meanOf(vals)}
								{@const meanX = rangeVal > 0 ? ((m - minVal) / rangeVal) * (N_BINS * 20) : -1}

								{@const ct = cardTitle(card)}
								<svg
									viewBox="0 0 {14 + N_BINS * 20} 148"
									class="w-full"
									style="aspect-ratio: {14 + N_BINS * 20} / 148"
									preserveAspectRatio="none"
									use:registerSvg={card.id}
								>
									<rect width="{14 + N_BINS * 20}" height="148" fill="white" />
									<!-- Title: dataset (line 1), column · type (line 2) -->
									<text x="{7 + N_BINS * 10}" y="13" text-anchor="middle" font-size="10" font-weight="600" fill="#1e293b">{ct.ds}</text>
									<text x="{7 + N_BINS * 10}" y="25" text-anchor="middle" font-size="9" fill="#64748b">{ct.col}</text>
									<!-- Y-axis label -->
									<text transform="rotate(-90, 8, 70)" text-anchor="middle" font-size="8" fill="#94a3b8">Count</text>
									<!-- Bars -->
									{#each bins as bin, i}
										{@const barH = maxCount > 0 ? (bin.count / maxCount) * 80 : 0}
										<rect
											x={14 + i * 20 + 0.5}
											y={110 - barH}
											width="19"
											height={barH}
											fill="#3b82f6"
											opacity="0.72"
											rx="1"
										>
											<title>{fmt(bin.lo)} – {fmt(bin.hi)}: {bin.count}</title>
										</rect>
									{/each}
									<!-- Baseline -->
									<line x1="14" y1="110" x2="{14 + N_BINS * 20}" y2="110" stroke="#e2e8f0" stroke-width="0.5" />
									<!-- Mean line -->
									{#if meanX >= 0}
										<line
											x1={14 + meanX} y1="28" x2={14 + meanX} y2="110"
											stroke="#ef4444" stroke-width="1.5" stroke-dasharray="3 2" opacity="0.85"
										/>
										<text x={Math.min(14 + meanX + 3, 14 + N_BINS * 20 - 40)} y="38" font-size="9" fill="#ef4444" opacity="0.85">mean</text>
									{/if}
									<!-- X-axis value labels -->
									<text x="16" y="122" font-size="8" fill="#94a3b8">{fmt(minVal)}</text>
									<text x="{7 + N_BINS * 10}" y="122" text-anchor="middle" font-size="8" fill="#94a3b8">{vals.length.toLocaleString()} values · mean {fmt(m)}</text>
									<text x="{12 + N_BINS * 20}" y="122" text-anchor="end" font-size="8" fill="#94a3b8">{fmt(maxVal)}</text>
									<!-- X-axis title -->
									<text x="{7 + N_BINS * 10}" y="138" text-anchor="middle" font-size="7" fill="#94a3b8">Value</text>
								</svg>
							{:else}
								{@const rows = getRanked(card.column, card.type === 'top_bar' ? 'top' : 'bottom')}
								{@const maxV = rows.reduce((a, r) => Math.max(a, Math.abs(r.v)), 0)}
								{@const barColor = card.type === 'top_bar' ? '#3b82f6' : '#fb923c'}
								{@const ct = cardTitle(card)}
								{@const svgH = rows.length * 22 + 42}
								<svg
									viewBox="0 0 400 {svgH}"
									style="width: 100%; aspect-ratio: 400 / {svgH}"
									use:registerSvg={card.id}
								>
									<rect width="400" height="{svgH}" fill="white" />
									<!-- Title: dataset (line 1), column · type (line 2) -->
									<text x="200" y="13" text-anchor="middle" font-size="10" font-weight="600" fill="#1e293b">{ct.ds}</text>
									<text x="200" y="25" text-anchor="middle" font-size="9" fill="#64748b">{ct.col}</text>
									<!-- Rows -->
									{#each rows as row, i}
										{@const barW = maxV > 0 ? (Math.abs(row.v) / maxV) * 182 : 0}
										<text x="25" y="{32 + i * 22 + 11}" dominant-baseline="middle" text-anchor="end" font-size="9" fill="#94a3b8">{i + 1}.</text>
										<text x="150" y="{32 + i * 22 + 11}" dominant-baseline="middle" text-anchor="end" font-size="9" fill="#64748b">{truncate(row.name, 22)}</text>
										<rect x="157" y="{32 + i * 22 + 3}" width="182" height="16" rx="2" fill="#f1f5f9" />
										<rect x="157" y="{32 + i * 22 + 3}" width="{barW}" height="16" rx="2" fill="{barColor}" opacity="0.8" />
										<text x="396" y="{32 + i * 22 + 11}" dominant-baseline="middle" text-anchor="end" font-size="9" fill="#1e293b" font-family="monospace">{fmt(row.v)}</text>
									{/each}
									<!-- X-axis label -->
									<text x="339" y="{svgH - 6}" text-anchor="end" font-size="7" fill="#94a3b8">Value →</text>
								</svg>
							{/if}

							{#if meta}
								<p class="mt-2 text-[10px] text-muted-foreground/60 truncate">{meta}</p>
							{/if}
						</div>
					</div>
				{/each}
			</div>

			<!-- Add chart -->
			{#if data.columns.length > 0}
				{#if showAddPicker}
					<div class="rounded-lg border bg-muted/30 p-4 space-y-3 max-w-xs">
						<p class="text-sm font-semibold">Add chart</p>
						<div class="space-y-2">
							<select bind:value={newCardCol} class="chart-select w-full">
								{#each Object.entries(data.col_groups) as [group, cols]}
									<optgroup label={group}>
										{#each cols as col}
											<option value={col}>{colLabel(col)}</option>
										{/each}
									</optgroup>
								{/each}
							</select>
							<select bind:value={newCardType} class="chart-select w-full">
								{#each CHART_TYPES as ct}
									<option value={ct.value}>{ct.label}</option>
								{/each}
							</select>
						</div>
						<div class="flex gap-2 items-center">
							<button onclick={addCard} class="chart-btn-primary">Add</button>
							<button onclick={() => (showAddPicker = false)} class="text-sm text-muted-foreground hover:text-foreground">Cancel</button>
						</div>
					</div>
				{:else}
					<button
						onclick={() => { showAddPicker = true; newCardCol = data.columns[0]; }}
						class="flex items-center gap-1.5 text-sm text-primary hover:underline"
					>
						<Plus class="h-4 w-4" />
						Add chart
					</button>
				{/if}
			{/if}
		{/if}
	</div>
</div>

<style>
	.chart-select {
		padding: 4px 7px;
		border: 1px solid #e2e8f0;
		border-radius: 5px;
		font-size: 12px;
		background: #fff;
		color: #1e293b;
		cursor: pointer;
	}
	.chart-select:focus { outline: 2px solid #3b82f6; outline-offset: -1px; }
	.chart-btn-primary {
		padding: 4px 12px;
		background: #3b82f6;
		color: #fff;
		border-radius: 5px;
		font-size: 12px;
		font-weight: 500;
	}
	.chart-btn-primary:hover { background: #2563eb; }
</style>
