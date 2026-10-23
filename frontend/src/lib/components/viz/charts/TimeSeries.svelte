<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import type { TimeSeriesCard } from '../chartTypes';
	import { fmt, getDatasetFieldTracks, getTemporalSeries, numericValue } from '$lib/viz';
	import { aidBase, aidTip, compact, niceScale, tickFormatFor, type DrawFn } from '$lib/charts/plot';
	import PlotFigure, { type FigureHandle } from '$lib/components/charts/PlotFigure.svelte';

	interface Props {
		data: VizPayload;
		card: TimeSeriesCard;
		/** Feature id highlighted across the scatter and time-series charts */
		highlightedFeature?: string | null;
		onHighlight?: (id: string | null) => void;
		handle?: FigureHandle | null;
	}
	let { data, card, highlightedFeature = null, onHighlight, handle = $bindable() }: Props = $props();

	/** "All features" draws at most this many lines */
	const MAX_LINES = 200;

	interface PeriodRow {
		period: string;
		mean: number | null;
		min: number | null;
		max: number | null;
		n: number;
	}

	interface FeaturePoint {
		id: string;
		name: string;
		period: string;
		value: number | null;
	}

	let series = $derived(getTemporalSeries(data, card.datasetKey, card.fieldTrack));
	let periods = $derived<PeriodRow[]>(
		series.map((e) => ({ period: e.temporal, mean: e.mean, min: e.min, max: e.max, n: e.values.length }))
	);
	let featureCount = $derived(Object.keys(data.features).length);

	// One point per feature per period; a missing value breaks that feature's line instead of joining across it
	let featurePoints = $derived<FeaturePoint[]>(
		card.aggregateMode === 'all'
			? Object.entries(data.features)
					.slice(0, MAX_LINES)
					.flatMap(([id, f]) => series.map((e) => ({ id, name: f.name, period: e.temporal, value: numericValue(f[e.col]) })))
			: []
	);

	let hasMultipleTracks = $derived(getDatasetFieldTracks(data, card.datasetKey).length > 1);
	let modeLabel = $derived(
		card.aggregateMode === 'all' ? 'all features' : card.aggregateMode === 'mean' ? 'mean' : 'mean and range'
	);
	let subtitle = $derived(`${hasMultipleTracks && card.fieldTrack ? card.fieldTrack + ' — ' : ''}Time series — ${modeLabel}`);

	const draw: DrawFn = ({ Plot, t, width }) => {
		const domain = periods.map((p) => p.period);
		const defined = periods.filter((p) => p.mean !== null);
		const lows = card.aggregateMode === 'all'
			? featurePoints.flatMap((p) => (p.value === null ? [] : [p.value]))
			: card.aggregateMode === 'band' ? defined.map((p) => p.min!) : defined.map((p) => p.mean!);
		const highs = card.aggregateMode === 'all'
			? lows
			: card.aggregateMode === 'band' ? defined.map((p) => p.max!) : defined.map((p) => p.mean!);
		const y = niceScale(Math.min(...lows, ...defined.map((p) => p.mean!)), Math.max(...highs, ...defined.map((p) => p.mean!)), 4);
		const crowded = width / domain.length < 44;
		const first = defined[0];
		const last = defined[defined.length - 1];
		const highlighted = featurePoints.filter((p) => p.id === highlightedFeature);

		const marks = [Plot.gridY(y.ticks, { stroke: t.grid, strokeOpacity: 1 })];
		if (card.aggregateMode === 'band') {
			marks.push(Plot.areaY(periods, { x: 'period', y1: 'min', y2: 'max', fill: t.series[0], fillOpacity: 0.2 }));
		}
		if (card.aggregateMode === 'all') {
			marks.push(
				Plot.lineY(featurePoints, {
					x: 'period',
					y: 'value',
					z: 'id',
					stroke: t.mutedForeground,
					strokeWidth: 1,
					strokeOpacity: highlightedFeature === null ? 0.35 : 0.15
				}),
				Plot.lineY(highlighted, { x: 'period', y: 'value', stroke: t.foreground, strokeWidth: 2.5 })
			);
		}
		marks.push(
			Plot.lineY(periods, { x: 'period', y: 'mean', stroke: t.series[0], strokeWidth: 2 }),
			Plot.dot(periods, { x: 'period', y: 'mean', fill: t.series[0], r: 3.5, stroke: t.edge, strokeWidth: 1.5 }),
			// End label only (§9.5)
			Plot.text(defined, Plot.selectLast({
				x: 'period',
				y: 'mean',
				text: (p: PeriodRow) => compact(p.mean!),
				dx: 8,
				textAnchor: 'start',
				fill: t.foreground,
				fontWeight: 700
			})),
			Plot.ruleX(periods, Plot.pointerX({ x: 'period', stroke: t.axis })),
			Plot.tip(
				periods,
				Plot.pointerX({
					x: 'period',
					y: 'mean',
					title: (p: PeriodRow) =>
						p.mean === null
							? `${p.period}\nNo values`
							: [p.period, `Mean ${fmt(p.mean)}`, `Min ${fmt(p.min)}, max ${fmt(p.max)}`, `n = ${p.n.toLocaleString()}`].join('\n'),
					...aidTip(t)
				})
			)
		);

		const plot = Plot.plot({
			...aidBase(t, width, 260),
			marginTop: 16,
			marginLeft: 52,
			marginRight: 52,
			marginBottom: crowded ? 56 : 36,
			ariaLabel: `${card.datasetKey}, ${subtitle}`,
			ariaDescription:
				first && last && first !== last
					? `The mean moves from ${fmt(first.mean)} in ${first.period} to ${fmt(last.mean)} in ${last.period}.`
					: `Mean values across ${domain.length} periods.`,
			x: { type: 'point', domain, tickSize: 0, label: null, inset: 8, tickRotate: crowded ? -35 : 0 },
			y: { domain: y.domain, ticks: y.ticks, tickFormat: tickFormatFor(y.ticks), tickSize: 0, label: null },
			marks
		});

		// In "all features" mode, click near a feature's line to highlight it here and in the scatter plot
		if (card.aggregateMode === 'all') {
			const svg = plot instanceof SVGSVGElement ? plot : plot.querySelector('svg');
			plot.addEventListener('click', (e) => {
				const event = e as MouseEvent;
				const xs = plot.scale('x');
				const ys = plot.scale('y');
				if (!svg || !xs?.apply || !ys?.apply) return;
				const box = svg.getBoundingClientRect();
				const mx = event.clientX - box.left;
				const my = event.clientY - box.top;
				let best: FeaturePoint | null = null;
				let bestD = 12; // px
				for (const p of featurePoints) {
					if (p.value === null) continue;
					const d = Math.hypot(xs.apply(p.period) - mx, ys.apply(p.value) - my);
					if (d < bestD) {
						bestD = d;
						best = p;
					}
				}
				if (best) onHighlight?.(best.id === highlightedFeature ? null : best.id);
			});
		}
		return plot;
	};

	let table = $derived({
		columns: [
			{ key: 'period', label: 'Period' },
			{ key: 'mean', label: 'Mean', numeric: true },
			{ key: 'min', label: 'Min', numeric: true },
			{ key: 'max', label: 'Max', numeric: true },
			{ key: 'n', label: 'Features', numeric: true }
		],
		rows: periods.map((p) => ({ ...p }))
	});
</script>

{#if series.length < 2}
	<p class="py-10 text-center text-sm text-muted-foreground">Not enough temporal columns in this dataset group.</p>
{:else}
	<PlotFigure
		title={card.datasetKey}
		{subtitle}
		caption={card.aggregateMode === 'all' && featureCount > MAX_LINES
			? `Showing the first ${MAX_LINES} of ${featureCount.toLocaleString()} features.`
			: undefined}
		{draw}
		{table}
		bind:handle
	/>
{/if}
