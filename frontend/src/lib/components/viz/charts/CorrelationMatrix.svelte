<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import type { CorrelationCard } from '../chartTypes';
	import { pearsonMatrix, fieldLabel } from '$lib/viz';

	interface Props {
		data: VizPayload;
		card: CorrelationCard;
		onCardUpdate?: (patch: Partial<CorrelationCard>) => void;
		onsvgready?: (svg: SVGSVGElement | null) => void;
	}
	let { data, card, onCardUpdate, onsvgready }: Props = $props();

	const CELL = 36, LEFT_PAD = 80, TOP_PAD = 80;

	function axisLabel(col: string) {
		const temporal = data.col_temporal[col];
		const s = temporal ? `${fieldLabel(col)} ${temporal}` : fieldLabel(col);
		return s.length > 12 ? s.slice(0, 11) + '…' : s;
	}

	function fullLabel(col: string) {
		const ds = data.col_dataset_titles[col];
		const field = fieldLabel(col);
		const temporal = data.col_temporal[col];
		return [ds, field, temporal].filter(Boolean).join(' · ');
	}

	function rToColor(r: number): string {
		if (r >= 0) {
			const t = r;
			return `rgb(${Math.round(241 + t * (29 - 241))},${Math.round(245 + t * (78 - 245))},${Math.round(248 + t * (216 - 248))})`;
		}
		const t = -r;
		return `rgb(${Math.round(241 + t * (220 - 241))},${Math.round(245 + t * (38 - 245))},${Math.round(248 + t * (38 - 248))})`;
	}

	let cols = $derived(card.columns);
	let matrix = $derived(cols.length >= 2 ? pearsonMatrix(data, cols) : []);
	let N = $derived(cols.length);
	let svgSize = $derived(N * CELL + LEFT_PAD + 8);

	let svgEl = $state<SVGSVGElement | undefined>();
	$effect(() => {
		if (svgEl) onsvgready?.(svgEl);
		return () => onsvgready?.(null);
	});

	let showColPicker = $state(false);

	function toggleCol(col: string, checked: boolean) {
		const next = checked ? [...card.columns, col] : card.columns.filter((c) => c !== col);
		onCardUpdate?.({ columns: next });
	}
</script>

<div class="space-y-2">
	<div class="flex items-center gap-2 px-1">
		<button
			onclick={() => (showColPicker = !showColPicker)}
			class="text-xs text-primary hover:underline"
		>
			{showColPicker ? 'Hide' : 'Edit'} columns ({cols.length} selected)
		</button>
		{#if cols.length > 15}
			<span class="text-xs text-amber-600">Select ≤ 15 columns for readability</span>
		{/if}
	</div>
	{#if showColPicker}
		<div class="max-h-48 overflow-y-auto rounded border bg-muted/20 p-2 space-y-1">
			{#each Object.entries(data.col_groups) as [group, groupCols]}
				<p class="text-[10px] font-semibold uppercase text-muted-foreground/70 mt-1">{group}</p>
				{#each groupCols as col}
					<label class="flex items-center gap-1.5 text-xs cursor-pointer" title={fullLabel(col)}>
						<input
							type="checkbox"
							checked={card.columns.includes(col)}
							onchange={(e) => toggleCol(col, (e.target as HTMLInputElement).checked)}
						/>
						{fieldLabel(col)}
						{#if data.col_temporal[col]}<span class="text-muted-foreground">·
							{data.col_temporal[col]}</span>{/if}
					</label>
				{/each}
			{/each}
		</div>
	{/if}
	{#if N < 2}
		<p class="text-center text-sm text-muted-foreground py-6">Select at least 2 columns.</p>
	{:else}
		<svg bind:this={svgEl} viewBox="0 0 {svgSize} {svgSize}" class="w-full" style="aspect-ratio: 1">
			<rect width={svgSize} height={svgSize} fill="white" />
			{#each cols as col, j}
				<text
					x={LEFT_PAD + j * CELL + CELL / 2}
					y={TOP_PAD - 4}
					text-anchor="start"
					font-size="9"
					fill="#64748b"
					transform="rotate(-45, {LEFT_PAD + j * CELL + CELL / 2}, {TOP_PAD - 4})"
				>{axisLabel(col)}<title>{fullLabel(col)}</title></text>
			{/each}
			{#each cols as col, i}
				<text x={LEFT_PAD - 4} y={TOP_PAD + i * CELL + CELL / 2 + 4} text-anchor="end" font-size="9" fill="#64748b"
				>{axisLabel(col)}<title>{fullLabel(col)}</title></text>
			{/each}
			{#each matrix as row, i}
				{#each row as r, j}
					<rect
						x={LEFT_PAD + j * CELL}
						y={TOP_PAD + i * CELL}
						width={CELL}
						height={CELL}
						fill={rToColor(r)}
					/>
					<text
						x={LEFT_PAD + j * CELL + CELL / 2}
						y={TOP_PAD + i * CELL + CELL / 2 + 4}
						text-anchor="middle"
						font-size="8"
						fill={Math.abs(r) > 0.5 ? 'white' : '#475569'}
					>
						{r.toFixed(2)}
					</text>
				{/each}
			{/each}
		</svg>
	{/if}
</div>
