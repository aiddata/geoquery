<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import { prettyColumn, detectBinary } from '$lib/viz';
	import { X, Plus, Download } from '@lucide/svelte';
	import { type ChartCard, type SingleColCard, type TimeSeriesCard, type ScatterCard, type CorrelationCard, CHART_TYPES } from './chartTypes';
	import Histogram from './charts/Histogram.svelte';
	import RankedBar from './charts/RankedBar.svelte';
	import TimeSeries from './charts/TimeSeries.svelte';
	import Scatter from './charts/Scatter.svelte';
	import BoxPlot from './charts/BoxPlot.svelte';

	interface Props {
		data: VizPayload;
	}
	let { data }: Props = $props();

	let chartCards = $state<ChartCard[]>([]);
	let showAddPicker = $state(false);
	let newCardCol = $state('');
	let newCardDatasetKey = $state('');
	let newCardType = $state<ChartCard['type']>('histogram');

	let columnsKey = $derived(data.columns.join('\x00'));
	let _lastKey = '';
	$effect(() => {
		const key = columnsKey;
		if (key === _lastKey) return;
		_lastKey = key;
		if (!data.columns.length) { chartCards = []; return; }

		const defaults: ChartCard[] = [];

		// detect temporal group with ≥3 temporal columns
		const temporalGroup = Object.entries(data.col_groups).find(([, cols]) =>
			cols.filter(c => data.col_temporal[c]).length >= 3
		);

		if (temporalGroup) {
			const [dk, cols] = temporalGroup;
			const temporalCols = cols.filter(c => data.col_temporal[c]);
			defaults.push({
				id: crypto.randomUUID(), type: 'time_series',
				datasetKey: dk, columns: temporalCols, aggregateMode: 'mean'
			} satisfies TimeSeriesCard);
		}

		const firstCol = data.columns[0];
		const firstVals = Object.values(data.features)
			.map(f => Number(f[firstCol]))
			.filter(n => !isNaN(n));
		const firstType: SingleColCard['type'] = detectBinary(firstVals) ? 'binary_bar' : 'histogram';
		defaults.push({ id: crypto.randomUUID(), type: firstType, column: firstCol } satisfies SingleColCard);

		if (!temporalGroup) {
			defaults.push({ id: crypto.randomUUID(), type: 'top_bar', column: firstCol } satisfies SingleColCard);
		}

		chartCards = defaults;
		newCardCol = firstCol;
		newCardDatasetKey = Object.keys(data.col_groups)[0] ?? '';
		newCardType = 'histogram';
	});

	function removeCard(id: string) {
		chartCards = chartCards.filter((c) => c.id !== id);
	}

	function updateCard(id: string, patch: Partial<ChartCard>) {
		chartCards = chartCards.map((c) => (c.id === id ? { ...c, ...patch } as ChartCard : c));
	}

	function addCard() {
		if (newCardType === 'time_series') {
			const cols = (data.col_groups[newCardDatasetKey] ?? []).filter(c => data.col_temporal[c]);
			chartCards = [...chartCards, {
				id: crypto.randomUUID(), type: 'time_series',
				datasetKey: newCardDatasetKey, columns: cols, aggregateMode: 'mean'
			} satisfies TimeSeriesCard];
		} else if (newCardType === 'scatter') {
			const firstCol = data.columns[0] ?? '';
			const secondCol = data.columns[1] ?? firstCol;
			chartCards = [...chartCards, {
				id: crypto.randomUUID(), type: 'scatter', xCol: firstCol, yCol: secondCol
			} satisfies ScatterCard];
		} else if (newCardType === 'correlation') {
			chartCards = [...chartCards, {
				id: crypto.randomUUID(), type: 'correlation', columns: data.columns.slice(0, 10)
			} satisfies CorrelationCard];
		} else if (newCardCol) {
			chartCards = [...chartCards, {
				id: crypto.randomUUID(), type: newCardType as SingleColCard['type'], column: newCardCol
			} satisfies SingleColCard];
		}
		showAddPicker = false;
	}

	const svgRefs = new Map<string, SVGSVGElement>();

	function makeSvgHandler(id: string) {
		return (svg: SVGSVGElement | null) => {
			if (svg) {
				svgRefs.set(id, svg);
			} else {
				svgRefs.delete(id);
			}
		};
	}

	function cardFilename(card: ChartCard): string {
		if (card.type === 'time_series') return `${card.datasetKey}_time_series.png`;
		if (card.type === 'scatter') return `${card.xCol}_vs_${card.yCol}_scatter.png`;
		if (card.type === 'correlation') return 'correlation_matrix.png';
		return `${card.column}_${card.type}.png`;
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
				a.download = cardFilename(card);
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
				URL.revokeObjectURL(pngUrl);
			}, 'image/png');
		};
		img.src = url;
	}

	function niceName(col: string): string {
		return prettyColumn(col).replace(/_/g, ' ');
	}

	function colLabel(col: string): string {
		const parts = [niceName(col), data.col_temporal[col]].filter(Boolean);
		return parts.join(' · ');
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
					<div class="rounded-lg border bg-card shadow-sm overflow-hidden">
						<!-- Card header -->
						<div class="flex items-center gap-2 px-3 py-2 border-b bg-muted/30">
							{#if card.type === 'histogram' || card.type === 'top_bar' || card.type === 'bottom_bar' || card.type === 'binary_bar' || card.type === 'box_plot'}
								{@const sc = card as SingleColCard}
								<select value={sc.column}
									onchange={(e) => updateCard(card.id, { column: (e.target as HTMLSelectElement).value } as Partial<SingleColCard>)}
									class="chart-select flex-1 min-w-0">
									{#each Object.entries(data.col_groups) as [group, cols]}
										<optgroup label={group}>
											{#each cols as col}<option value={col}>{colLabel(col)}</option>{/each}
										</optgroup>
									{/each}
								</select>
								<select value={card.type}
									onchange={(e) => updateCard(card.id, { type: (e.target as HTMLSelectElement).value as SingleColCard['type'] } as Partial<SingleColCard>)}
									class="chart-select shrink-0" style="width: auto">
									{#each CHART_TYPES.filter(ct => !ct.multi) as ct}
										<option value={ct.value}>{ct.label}</option>
									{/each}
								</select>
							{:else if card.type === 'time_series'}
								{@const tc = card as TimeSeriesCard}
								<select value={tc.datasetKey}
									onchange={(e) => {
										const dk = (e.target as HTMLSelectElement).value;
										const cols = (data.col_groups[dk] ?? []).filter(c => data.col_temporal[c]);
										updateCard(card.id, { datasetKey: dk, columns: cols } as Partial<TimeSeriesCard>);
									}}
									class="chart-select flex-1 min-w-0">
									{#each Object.keys(data.col_groups) as group}
										<option value={group}>{group}</option>
									{/each}
								</select>
								<select value={tc.aggregateMode}
									onchange={(e) => updateCard(card.id, { aggregateMode: (e.target as HTMLSelectElement).value as TimeSeriesCard['aggregateMode'] } as Partial<TimeSeriesCard>)}
									class="chart-select shrink-0" style="width: auto">
									<option value="all">All features</option>
									<option value="mean">Mean only</option>
									<option value="band">Mean + range</option>
								</select>
							{:else if card.type === 'scatter'}
								{@const sc2 = card as ScatterCard}
								<select value={sc2.xCol}
									onchange={(e) => updateCard(card.id, { xCol: (e.target as HTMLSelectElement).value } as Partial<ScatterCard>)}
									class="chart-select flex-1 min-w-0">
									{#each Object.entries(data.col_groups) as [group, cols]}
										<optgroup label={group}>
											{#each cols as col}<option value={col}>{colLabel(col)}</option>{/each}
										</optgroup>
									{/each}
								</select>
								<span class="text-xs text-muted-foreground shrink-0">vs</span>
								<select value={sc2.yCol}
									onchange={(e) => updateCard(card.id, { yCol: (e.target as HTMLSelectElement).value } as Partial<ScatterCard>)}
									class="chart-select flex-1 min-w-0">
									{#each Object.entries(data.col_groups) as [group, cols]}
										<optgroup label={group}>
											{#each cols as col}<option value={col}>{colLabel(col)}</option>{/each}
										</optgroup>
									{/each}
								</select>
							{:else if card.type === 'correlation'}
								{@const cc = card as CorrelationCard}
								<span class="text-xs text-muted-foreground flex-1">{cc.columns.length} columns selected</span>
							{/if}
							<button onclick={() => exportCard(card)} class="shrink-0 text-muted-foreground hover:text-foreground" title="Save as PNG">
								<Download class="h-3.5 w-3.5" />
							</button>
							<button onclick={() => removeCard(card.id)} class="shrink-0 text-muted-foreground hover:text-destructive" title="Remove chart">
								<X class="h-3.5 w-3.5" />
							</button>
						</div>

						<!-- Chart body -->
						<div class="p-3">
							{#if card.type === 'histogram'}
								<Histogram {data} card={card as SingleColCard} onsvgready={makeSvgHandler(card.id)} />
							{:else if card.type === 'top_bar' || card.type === 'bottom_bar'}
								<RankedBar {data} card={card as SingleColCard} onsvgready={makeSvgHandler(card.id)} />
							{:else if card.type === 'time_series'}
								<TimeSeries {data} card={card as TimeSeriesCard} onsvgready={makeSvgHandler(card.id)} />
							{:else if card.type === 'scatter'}
								<Scatter {data} card={card as ScatterCard} onsvgready={makeSvgHandler(card.id)} />
							{:else if card.type === 'box_plot'}
								<BoxPlot {data} card={card as SingleColCard} onsvgready={makeSvgHandler(card.id)} />
							{:else}
								<div class="flex h-32 items-center justify-center text-sm text-muted-foreground">
									Chart type not yet implemented.
								</div>
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
							<select bind:value={newCardType} class="chart-select w-full">
								{#each CHART_TYPES as ct}<option value={ct.value}>{ct.label}</option>{/each}
							</select>
							{#if !CHART_TYPES.find(t => t.value === newCardType)?.multi}
								<select bind:value={newCardCol} class="chart-select w-full">
									{#each Object.entries(data.col_groups) as [group, cols]}
										<optgroup label={group}>
											{#each cols as col}<option value={col}>{colLabel(col)}</option>{/each}
										</optgroup>
									{/each}
								</select>
							{:else if newCardType === 'time_series'}
								<select bind:value={newCardDatasetKey} class="chart-select w-full">
									{#each Object.keys(data.col_groups) as group}<option value={group}>{group}</option>{/each}
								</select>
							{:else}
								<p class="text-xs text-muted-foreground">Configure column selection in the card after adding.</p>
							{/if}
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
