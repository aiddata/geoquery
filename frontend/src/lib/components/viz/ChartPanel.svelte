<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import { prettyColumn } from '$lib/viz';
	import { X, Plus, Download } from '@lucide/svelte';
	import { type ChartCard, type SingleColCard, CHART_TYPES } from './chartTypes';
	import Histogram from './charts/Histogram.svelte';
	import RankedBar from './charts/RankedBar.svelte';

	interface Props {
		data: VizPayload;
	}
	let { data }: Props = $props();

	let chartCards = $state<ChartCard[]>([]);
	let showAddPicker = $state(false);
	let newCardCol = $state('');
	let newCardType = $state<SingleColCard['type']>('histogram');

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

	function updateCard(id: string, patch: Partial<ChartCard>) {
		chartCards = chartCards.map((c) => (c.id === id ? { ...c, ...patch } : c));
	}

	function addCard() {
		if (!newCardCol) return;
		chartCards = [...chartCards, { id: crypto.randomUUID(), type: newCardType, column: newCardCol }];
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
				const singleCard = card as SingleColCard;
				a.download = `${singleCard.column}_${card.type}.png`;
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

	function cardTitle(card: ChartCard): { ds: string; col: string } {
		const singleCard = card as SingleColCard;
		const ds = data.col_dataset_titles[singleCard.column] ?? '';
		const typeLabel = CHART_TYPES.find(t => t.value === card.type)?.label ?? '';
		const temporal = data.col_temporal[singleCard.column];
		const colPart = [niceName(singleCard.column), temporal].filter(Boolean).join(' · ');
		return { ds: ds || niceName(singleCard.column), col: `${colPart} — ${typeLabel}` };
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
					{@const singleCard = card as SingleColCard}
					{@const dsTitle = data.col_dataset_titles[singleCard.column] ?? ''}
					{@const temporal = data.col_temporal[singleCard.column] ?? ''}
					{@const meta = [dsTitle, temporal].filter(Boolean).join(' · ')}

					<div class="rounded-lg border bg-card shadow-sm overflow-hidden">
						<!-- Card header -->
						<div class="flex items-center gap-2 px-3 py-2 border-b bg-muted/30">
							<select
								value={singleCard.column}
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
								{#each CHART_TYPES.filter(ct => !ct.multi) as ct}
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
							{#if card.type === 'histogram'}
								<Histogram {data} card={card as SingleColCard} onsvgready={makeSvgHandler(card.id)} />
							{:else if card.type === 'top_bar' || card.type === 'bottom_bar'}
								<RankedBar {data} card={card as SingleColCard} onsvgready={makeSvgHandler(card.id)} />
							{:else}
								<div class="flex h-32 items-center justify-center text-sm text-muted-foreground">
									Chart type not yet implemented.
								</div>
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
								{#each CHART_TYPES.filter(ct => !ct.multi) as ct}
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
