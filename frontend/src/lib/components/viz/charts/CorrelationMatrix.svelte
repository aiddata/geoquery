<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import type { CorrelationCard } from '../chartTypes';
	import { fieldLabel, pearsonMatrix } from '$lib/viz';
	import { aidBase, aidTip, labelWidth, type DrawFn } from '$lib/charts/plot';
	import PlotFigure, { type FigureHandle } from '$lib/components/charts/PlotFigure.svelte';
	import { Button } from '$lib/components/ui/button';
	import { Checkbox } from '$lib/components/ui/checkbox';

	interface Props {
		data: VizPayload;
		card: CorrelationCard;
		onCardUpdate?: (patch: Partial<CorrelationCard>) => void;
		handle?: FigureHandle | null;
	}
	let { data, card, onCardUpdate, handle = $bindable() }: Props = $props();

	// The §3 diverging ramp in five classes; the middle class is "little or no correlation" (§11)
	const THRESHOLDS = [-0.6, -0.2, 0.2, 0.6];

	interface Cell {
		row: string;
		col: string;
		r: number;
	}

	function shortLabel(col: string) {
		const temporal = data.col_temporal[col];
		const s = temporal ? `${fieldLabel(col)} ${temporal}` : fieldLabel(col);
		return s.length > 18 ? s.slice(0, 17) + '…' : s;
	}

	function fullLabel(col: string) {
		return [data.col_dataset_titles[col], fieldLabel(col), data.col_temporal[col]].filter(Boolean).join(' · ');
	}

	function step(r: number): number {
		let i = 0;
		while (i < THRESHOLDS.length && r >= THRESHOLDS[i]) i++;
		return i;
	}

	const rText = (r: number) => (Number.isNaN(r) ? 'n/a' : r.toFixed(2));

	let cols = $derived(card.columns);
	let matrix = $derived(cols.length >= 2 ? pearsonMatrix(data, cols) : []);
	let cells = $derived<Cell[]>(cols.flatMap((row, i) => cols.map((col, j) => ({ row, col, r: matrix[i][j] }))));

	let showColPicker = $state(false);

	function toggleCol(col: string, checked: boolean) {
		const next = checked ? [...card.columns, col] : card.columns.filter((c) => c !== col);
		onCardUpdate?.({ columns: next });
	}

	const draw: DrawFn = ({ Plot, t, width }) => {
		const widest = labelWidth(t, cols.map(shortLabel));
		const marginLeft = Math.min(170, widest + 12);
		// Column labels are rotated 40°, so they need about sin(40°) of their width above the grid
		const marginTop = Math.min(130, widest * 0.65 + 16);
		const cellSize = Math.min(56, (width - marginLeft - 8) / cols.length);
		const offDiagonal = cells.filter((c) => c.row < c.col && !Number.isNaN(c.r));
		const strongest = offDiagonal.reduce<Cell | null>((a, c) => (!a || Math.abs(c.r) > Math.abs(a.r) ? c : a), null);
		const label = (c: Cell) => (cellSize >= 34 ? rText(c.r) : '');

		return Plot.plot({
			...aidBase(t, Math.min(width, marginLeft + cellSize * cols.length + 8), marginTop + cellSize * cols.length + 8),
			marginTop,
			marginLeft,
			marginRight: 8,
			marginBottom: 8,
			ariaLabel: `Correlation matrix of ${cols.length} columns`,
			ariaDescription: strongest
				? `The strongest correlation is between ${fieldLabel(strongest.row)} and ${fieldLabel(strongest.col)}, r = ${strongest.r.toFixed(2)}.`
				: 'No correlations could be computed.',
			x: { domain: cols, axis: 'top', tickSize: 0, tickRotate: -40, tickFormat: shortLabel, label: null },
			y: { domain: cols, tickSize: 0, tickFormat: shortLabel, label: null },
			color: { type: 'threshold', domain: THRESHOLDS, range: t.div, unknown: t.noValue, legend: true, label: "Pearson's r" },
			marks: [
				Plot.cell(cells, { x: 'col', y: 'row', fill: (c: Cell) => (Number.isNaN(c.r) ? null : c.r), stroke: t.edge, strokeWidth: 1, inset: 0.5 }),
				// Coefficients in each step's ink (§3); undefined ones on the no-value fill
				Plot.text(cells, {
					x: 'col',
					y: 'row',
					text: label,
					fill: (c: Cell) => (Number.isNaN(c.r) ? t.forest : t.divInk[step(c.r)]),
					fontWeight: 700
				}),
				Plot.tip(
					cells,
					Plot.pointer({
						x: 'col',
						y: 'row',
						title: (c: Cell) => `${fullLabel(c.row)}\n${fullLabel(c.col)}\nr = ${rText(c.r)}`,
						...aidTip(t)
					})
				)
			]
		});
	};

	let table = $derived({
		columns: [{ key: 'row', label: 'Column' }, ...cols.map((c) => ({ key: c, label: shortLabel(c), numeric: true, format: (v: unknown) => rText(v as number) }))],
		rows: cols.map((row, i) => ({ row: fullLabel(row), ...Object.fromEntries(cols.map((c, j) => [c, matrix[i][j]])) }))
	});
</script>

{#snippet picker()}
	<div class="space-y-2">
		<div class="flex items-center gap-2">
			<Button variant="link" size="xs" class="px-0" onclick={() => (showColPicker = !showColPicker)} aria-expanded={showColPicker}>
				{showColPicker ? 'Hide' : 'Edit'} columns ({cols.length} selected)
			</Button>
			{#if cols.length > 15}
				<span class="text-xs text-warning-text">Select 15 or fewer columns for readability</span>
			{/if}
		</div>
		{#if showColPicker}
			<div class="max-h-48 space-y-1 overflow-y-auto rounded-md bg-muted p-2">
				{#each Object.entries(data.col_groups) as [group, groupCols] (group)}
					<p class="mt-1 text-xs font-bold text-muted-foreground">{group}</p>
					{#each groupCols as col (col)}
						<label class="flex cursor-pointer items-center gap-2 text-sm" title={fullLabel(col)}>
							<Checkbox checked={card.columns.includes(col)} onCheckedChange={(checked) => toggleCol(col, checked)} />
							{fieldLabel(col)}
							{#if data.col_temporal[col]}<span class="text-muted-foreground">· {data.col_temporal[col]}</span>{/if}
						</label>
					{/each}
				{/each}
			</div>
		{/if}
	</div>
{/snippet}

{#if cols.length < 2}
	{@render picker()}
	<p class="py-6 text-center text-sm text-muted-foreground">Select at least 2 columns.</p>
{:else}
	<PlotFigure
		title="Correlation matrix"
		subtitle="Pearson's r between columns, over features with values in both"
		controls={picker}
		{draw}
		{table}
		bind:handle
	/>
{/if}
