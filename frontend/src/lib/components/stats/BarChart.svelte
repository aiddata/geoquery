<script lang="ts">
	import type { StatsPoint } from '$lib/api';
	import { aidBase, aidTip, barInset, niceScale, tickFormatFor, type DrawFn } from '$lib/charts/plot';
	import PlotFigure from '$lib/components/charts/PlotFigure.svelte';

	interface Props {
		data: StatsPoint[];
		/** Which chart series color (1–4) the columns use */
		series?: 1 | 2 | 3 | 4;
		/** What a count counts, e.g. "requests" */
		label?: string;
		/** Accessible name; the card around the chart shows its visible title */
		title: string;
	}

	let { data, series = 1, label = 'items', title }: Props = $props();

	const MARGIN_LEFT = 52;
	const MARGIN_RIGHT = 12;

	const draw: DrawFn = ({ Plot, t, width }) => {
		const counts = data.map((d) => d.count);
		const y = niceScale(0, Math.max(1, ...counts), 4);
		const band = (width - MARGIN_LEFT - MARGIN_RIGHT) / data.length;
		const inset = barInset(band);
		// Very narrow columns (a year of days) drop the edge and rounding, which would otherwise swamp the fill
		const narrow = band - inset * 2 < 6;
		const labelEvery = Math.max(1, Math.ceil(data.length / 12));
		const crowded = band * labelEvery < 72;
		const peak = data.reduce((a, d) => (d.count > a.count ? d : a));
		const total = counts.reduce((a, b) => a + b, 0);

		return Plot.plot({
			...aidBase(t, width, 300),
			marginTop: 16,
			marginLeft: MARGIN_LEFT,
			marginRight: MARGIN_RIGHT,
			marginBottom: crowded ? 64 : 32,
			ariaLabel: title,
			ariaDescription: `${total.toLocaleString()} ${label} across ${data.length} periods, peaking at ${peak.count.toLocaleString()} on ${peak.date}.`,
			x: {
				domain: data.map((d) => d.date),
				padding: 0,
				ticks: data.filter((_, i) => i % labelEvery === 0).map((d) => d.date),
				tickSize: 0,
				tickRotate: crowded ? -35 : 0,
				label: null
			},
			y: { domain: y.domain, ticks: y.ticks, tickFormat: tickFormatFor(y.ticks), tickSize: 0, label: null },
			marks: [
				Plot.gridY(y.ticks.slice(1), { stroke: t.grid, strokeOpacity: 1 }),
				Plot.barY(data, {
					x: 'date',
					y: 'count',
					fill: t.series[series - 1],
					insetLeft: Math.max(inset, narrow ? 0.25 : 0.5),
					insetRight: Math.max(inset, narrow ? 0.25 : 0.5),
					...(narrow ? {} : { stroke: t.edge, strokeWidth: 1, ry2: 4 })
				}),
				Plot.ruleY([0], { stroke: t.axis }),
				Plot.tip(
					data,
					Plot.pointerX({
						x: 'date',
						y: 'count',
						title: (d: StatsPoint) => `${d.date}\n${d.count.toLocaleString()} ${label}`,
						...aidTip(t)
					})
				)
			]
		});
	};

	let table = $derived({
		columns: [
			{ key: 'date', label: 'Date' },
			{ key: 'count', label: label.charAt(0).toUpperCase() + label.slice(1), numeric: true }
		],
		rows: data.map((d) => ({ ...d }))
	});
</script>

{#if data.length === 0}
	<div class="flex h-72 items-center justify-center text-sm text-muted-foreground">
		No data for this selection.
	</div>
{:else}
	<PlotFigure {title} titleHidden {draw} {table} />
{/if}
