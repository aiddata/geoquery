<script lang="ts">
	import type { StatsPoint } from '#lib/api.js';
	import { aidBase, aidTip, barInset, niceScale, tickFormatFor, type DrawFn } from '#lib/charts/plot.js';
	import PlotFigure from '#lib/components/charts/PlotFigure.svelte';

	interface Props {
		data: StatsPoint[];
		/** Which chart series color (1–4) the columns use */
		series?: 1 | 2 | 3 | 4;
		/** What a count counts, e.g. "requests" */
		label?: string;
		/** Accessible name; the card around the chart shows its visible title */
		title: string;
		/** A second series stacked under `data`, e.g. requests from earlier versions */
		earlier?: StatsPoint[];
		/** Legend name for `earlier`, and for `data` when both are shown */
		earlierLabel?: string;
		currentLabel?: string;
		/** A period (in the chart's own date format) to mark with a dashed line */
		cutover?: string | null;
		cutoverLabel?: string;
	}

	let {
		data: current,
		series = 1,
		label = 'items',
		title,
		earlier = [],
		earlierLabel = 'Earlier',
		currentLabel = 'Current',
		cutover = null,
		cutoverLabel = ''
	}: Props = $props();

	const stacked = $derived(earlier.length > 0);

	// One point per period with both parts, so totals, the tip and the table
	// line up whether or not the earlier series is shown.
	type Point = StatsPoint & { current: number; earlier: number };
	const data = $derived.by<Point[]>(() => {
		const byDate = new Map<string, Point>();
		const at = (date: string) => {
			let p = byDate.get(date);
			if (!p) byDate.set(date, (p = { date, count: 0, current: 0, earlier: 0 }));
			return p;
		};
		for (const d of current) { const p = at(d.date); p.current += d.count; p.count += d.count; }
		for (const d of earlier) { const p = at(d.date); p.earlier += d.count; p.count += d.count; }
		return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
	});

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
		// Stacked bars: earlier first (at the bottom), then current
		const parts = stacked
			? data.flatMap((d) => [
					{ date: d.date, count: d.earlier, source: earlierLabel },
					{ date: d.date, count: d.current, source: currentLabel }
				])
			: data.map((d) => ({ date: d.date, count: d.count, source: currentLabel }));
		const cutoverAt = cutover == null ? -1 : data.findIndex((d) => d.date === cutover);
		const showCutover = cutoverAt >= 0;
		// Label on whichever side of the line has room
		const labelLeft = cutoverAt > data.length / 2;

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
			color: {
				domain: [earlierLabel, currentLabel],
				range: [t.series[series % 4], t.series[series - 1]],
				legend: stacked
			},
			marks: [
				Plot.gridY(y.ticks.slice(1), { stroke: t.grid, strokeOpacity: 1 }),
				Plot.barY(parts, {
					x: 'date',
					y: 'count',
					fill: 'source',
					order: [earlierLabel, currentLabel],
					insetLeft: Math.max(inset, narrow ? 0.25 : 0.5),
					insetRight: Math.max(inset, narrow ? 0.25 : 0.5),
					...(narrow ? {} : { stroke: t.edge, strokeWidth: 1, ry2: 4 })
				}),
				Plot.ruleY([0], { stroke: t.axis }),
				...(showCutover
					? [
							Plot.ruleX([cutover], { stroke: t.axis, strokeDasharray: '4,3', strokeWidth: 1.5 }),
							Plot.text([cutover], {
								x: (d: string) => d,
								frameAnchor: 'top',
								textAnchor: labelLeft ? 'end' : 'start',
								dx: labelLeft ? -6 : 6,
								dy: 2,
								text: () => cutoverLabel,
								fill: t.mutedForeground
							})
						]
					: []),
				Plot.tip(
					data,
					Plot.pointerX({
						x: 'date',
						y: 'count',
						title: (d: Point) =>
							stacked && d.earlier && d.current
								? `${d.date}\n${d.count.toLocaleString()} ${label}\n${d.current.toLocaleString()} ${currentLabel.toLowerCase()}, ${d.earlier.toLocaleString()} ${earlierLabel.toLowerCase()}`
								: `${d.date}\n${d.count.toLocaleString()} ${label}`,
						...aidTip(t)
					})
				)
			]
		});
	};

	let table = $derived({
		columns: [
			{ key: 'date', label: 'Date' },
			...(stacked
				? [
						{ key: 'current', label: currentLabel, numeric: true },
						{ key: 'earlier', label: earlierLabel, numeric: true }
					]
				: []),
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
