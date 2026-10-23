<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import type { ScatterCard } from '../chartTypes';
	import { fieldLabel, fmt, numericValue, pearsonCorrelation } from '$lib/viz';
	import { aidBase, aidTip, capCategories, niceScale, SYMBOLS, tickFormatFor, type DrawFn } from '$lib/charts/plot';
	import PlotFigure, { type FigureHandle } from '$lib/components/charts/PlotFigure.svelte';

	interface Props {
		data: VizPayload;
		card: ScatterCard;
		/** Feature id highlighted across the scatter and time-series charts */
		highlightedFeature?: string | null;
		onHighlight?: (id: string | null) => void;
		handle?: FigureHandle | null;
	}
	let { data, card, highlightedFeature = null, onHighlight, handle = $bindable() }: Props = $props();

	interface Point {
		id: string;
		name: string;
		fc: string;
		group: string;
		x: number;
		y: number;
	}

	function axisLabel(col: string, ds: string, otherDs: string): string {
		const temporal = data.col_temporal[col];
		const withTime = temporal ? `${fieldLabel(col)} · ${temporal}` : fieldLabel(col);
		// Only name the dataset when the two columns come from different datasets
		return ds !== otherDs ? `${ds} · ${withTime}` : withTime;
	}

	let fcs = $derived([...new Set(Object.values(data.features).map((f) => f.fc))].sort());
	// At most four series; past four, the rest fold into "Other" (§9.2)
	let groups = $derived(capCategories(fcs));

	let points = $derived(
		Object.entries(data.features).flatMap(([id, f]): Point[] => {
			const x = numericValue(f[card.xCol]);
			const y = numericValue(f[card.yCol]);
			if (x === null || y === null) return [];
			return [{ id, name: f.name, fc: f.fc, group: groups.of(f.fc), x, y }];
		})
	);

	let dsX = $derived(data.col_dataset_titles[card.xCol] ?? '');
	let dsY = $derived(data.col_dataset_titles[card.yCol] ?? '');
	let title = $derived(dsX === dsY ? dsX || fieldLabel(card.xCol) : `${dsX} × ${dsY}`);
	let subtitle = $derived(`${fieldLabel(card.xCol)} vs ${fieldLabel(card.yCol)} — Scatter plot`);

	const draw: DrawFn = ({ Plot, t, width }) => {
		const x = niceScale(Math.min(...points.map((p) => p.x)), Math.max(...points.map((p) => p.x)), width < 420 ? 3 : 5);
		const y = niceScale(Math.min(...points.map((p) => p.y)), Math.max(...points.map((p) => p.y)), 4);
		const r = pearsonCorrelation(points.map((p) => p.x), points.map((p) => p.y));
		const showLegend = groups.domain.length > 1;
		const dim = (p: Point) => (highlightedFeature === null || p.id === highlightedFeature ? 1 : 0.15);

		const plot = Plot.plot({
			...aidBase(t, width, 300),
			marginTop: 28, // room for the y-axis label above the top tick
			marginLeft: 52,
			marginRight: 16,
			marginBottom: 40,
			ariaLabel: `Scatter plot of ${fieldLabel(card.xCol)} against ${fieldLabel(card.yCol)}`,
			ariaDescription: `${points.length.toLocaleString()} features. ${Number.isNaN(r) ? 'The correlation is undefined.' : `Pearson's r is ${r.toFixed(2)}.`}`,
			x: { domain: x.domain, ticks: x.ticks, tickFormat: tickFormatFor(x.ticks), tickSize: 0, label: axisLabel(card.xCol, dsX, dsY), labelArrow: 'none' },
			y: { domain: y.domain, ticks: y.ticks, tickFormat: tickFormatFor(y.ticks), tickSize: 0, label: axisLabel(card.yCol, dsY, dsX), labelArrow: 'none' },
			// Color paired with shape, so each boundary set is identifiable without color (§3, §9.4).
			// The symbol legend draws both, so the color scale has none of its own.
			color: { domain: groups.domain, range: t.series.slice(0, groups.domain.length) },
			symbol: { domain: groups.domain, range: SYMBOLS.slice(0, groups.domain.length), legend: showLegend },
			marks: [
				Plot.gridY(y.ticks, { stroke: t.grid, strokeOpacity: 1 }),
				Plot.gridX(x.ticks, { stroke: t.grid, strokeOpacity: 1 }),
				Plot.dot(points, {
					x: 'x',
					y: 'y',
					fill: 'group',
					symbol: 'group',
					r: 5,
					stroke: t.edge,
					strokeWidth: 1.5,
					fillOpacity: dim,
					strokeOpacity: dim
				}),
				Plot.tip(
					points,
					Plot.pointer({
						x: 'x',
						y: 'y',
						title: (p: Point) => `${p.name}\n${p.fc}\n${fieldLabel(card.xCol)}: ${fmt(p.x)}\n${fieldLabel(card.yCol)}: ${fmt(p.y)}`,
						...aidTip(t)
					})
				)
			]
		});

		// Click the pointed feature to highlight it here and in the time series; click again to clear
		plot.addEventListener('click', () => {
			const p = (plot as unknown as { value?: Point | null }).value;
			if (p) onHighlight?.(p.id === highlightedFeature ? null : p.id);
		});
		return plot;
	};

	let table = $derived({
		columns: [
			{ key: 'name', label: 'Name' },
			{ key: 'fc', label: 'Boundary set' },
			{ key: 'x', label: fieldLabel(card.xCol), numeric: true },
			{ key: 'y', label: fieldLabel(card.yCol), numeric: true }
		],
		rows: points.map((p) => ({ name: p.name, fc: p.fc, x: p.x, y: p.y }))
	});
</script>

{#if points.length === 0}
	<p class="py-10 text-center text-sm text-muted-foreground">No paired values for these columns.</p>
{:else}
	<PlotFigure
		{title}
		{subtitle}
		caption={fcs.length > 4 ? `${fcs.length - 3} boundary sets are grouped as "Other".` : undefined}
		{draw}
		{table}
		bind:handle
	/>
{/if}
