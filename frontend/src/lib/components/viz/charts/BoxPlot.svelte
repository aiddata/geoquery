<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import type { SingleColCard } from '../chartTypes';
	import { fmt, numericValue } from '$lib/viz';
	import { aidBase, aidTip, barInset, niceScale, tickFormatFor, type DrawFn } from '$lib/charts/plot';
	import { columnCaption, columnLabel } from '$lib/charts/labels';
	import PlotFigure, { type FigureHandle } from '$lib/components/charts/PlotFigure.svelte';

	interface Props {
		data: VizPayload;
		card: SingleColCard;
		handle?: FigureHandle | null;
	}
	let { data, card, handle = $bindable() }: Props = $props();

	interface Box {
		fc: string;
		n: number;
		min: number;
		max: number;
		q1: number;
		median: number;
		q3: number;
		whiskerLo: number;
		whiskerHi: number;
		outliers: number[];
	}

	// Linear interpolation between order statistics, as d3.quantile and Plot's boxY do
	function quantile(sorted: number[], q: number): number {
		const pos = (sorted.length - 1) * q;
		const lo = Math.floor(pos),
			hi = Math.ceil(pos);
		return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
	}

	function getBoxes(): Box[] {
		const byFc = new Map<string, number[]>();
		for (const f of Object.values(data.features)) {
			const v = numericValue(f[card.column]);
			if (v === null) continue;
			const vals = byFc.get(f.fc) ?? [];
			vals.push(v);
			byFc.set(f.fc, vals);
		}
		return [...byFc.entries()].map(([fc, vals]) => {
			const sorted = [...vals].sort((a, b) => a - b);
			const q1 = quantile(sorted, 0.25),
				median = quantile(sorted, 0.5),
				q3 = quantile(sorted, 0.75);
			const iqr = q3 - q1;
			// Tukey whiskers: the furthest values within 1.5 × IQR of the box
			const whiskerLo = sorted.find((v) => v >= q1 - 1.5 * iqr) ?? sorted[0];
			const whiskerHi = [...sorted].reverse().find((v) => v <= q3 + 1.5 * iqr) ?? sorted[sorted.length - 1];
			return {
				fc,
				n: sorted.length,
				min: sorted[0],
				max: sorted[sorted.length - 1],
				q1,
				median,
				q3,
				whiskerLo,
				whiskerHi,
				outliers: sorted.filter((v) => v < whiskerLo || v > whiskerHi)
			};
		});
	}

	let boxes = $derived(getBoxes());
	let caption = $derived(columnCaption(data, card.column, 'Box plot by boundary set'));

	const draw: DrawFn = ({ Plot, t, width }) => {
		const height = 260;
		const marginLeft = 52;
		const y = niceScale(Math.min(...boxes.map((b) => b.min)), Math.max(...boxes.map((b) => b.max)), 4);
		const band = (width - marginLeft - 16) / boxes.length;
		const inset = barInset(band, 40);
		const outliers = boxes.flatMap((b) => b.outliers.map((value) => ({ fc: b.fc, value })));
		const widest = boxes.reduce((a, b) => (b.q3 - b.q1 > a.q3 - a.q1 ? b : a));

		return Plot.plot({
			...aidBase(t, width, height),
			marginTop: 28, // room for the y-axis label above the top tick
			marginLeft,
			marginRight: 16,
			ariaLabel: `Box plot of ${caption.title} by boundary set`,
			ariaDescription: boxes
				.map((b) => `${b.fc}: median ${fmt(b.median)}, middle half ${fmt(b.q1)} to ${fmt(b.q3)}`)
				.join('; ') + `. ${widest.fc} varies the most.`,
			x: { domain: boxes.map((b) => b.fc), padding: 0, tickSize: 0, label: null, tickRotate: band < 72 ? -35 : 0 },
			y: { domain: y.domain, ticks: y.ticks, tickFormat: tickFormatFor(y.ticks), tickSize: 0, label: columnLabel(data, card.column), labelArrow: 'none' },
			marks: [
				Plot.gridY(y.ticks, { stroke: t.grid, strokeOpacity: 1 }),
				Plot.ruleX(boxes, { x: 'fc', y1: 'whiskerLo', y2: 'whiskerHi', stroke: t.foreground }),
				// The box follows the bar settings (§11)
				Plot.barY(boxes, {
					x: 'fc',
					y1: 'q1',
					y2: 'q3',
					fill: t.series[0],
					stroke: t.edge,
					strokeWidth: 1,
					insetLeft: inset,
					insetRight: inset,
					r: 4
				}),
				Plot.tickY(boxes, { x: 'fc', y: 'median', stroke: t.ink[0], strokeWidth: 2, insetLeft: inset + 2, insetRight: inset + 2 }),
				// Outliers follow the point settings (§9.4)
				Plot.dot(outliers, { x: 'fc', y: 'value', r: 5, fill: t.series[0], stroke: t.edge, strokeWidth: 1.5 }),
				Plot.tip(
					boxes,
					Plot.pointerX({
						x: 'fc',
						y: 'median',
						title: (b: Box) =>
							[b.fc, `Median ${fmt(b.median)}`, `Q1–Q3 ${fmt(b.q1)} – ${fmt(b.q3)}`, `Min ${fmt(b.min)}, max ${fmt(b.max)}`, `n = ${b.n.toLocaleString()}`].join('\n'),
						...aidTip(t)
					})
				)
			]
		});
	};

	let table = $derived({
		columns: [
			{ key: 'fc', label: 'Boundary set' },
			{ key: 'n', label: 'n', numeric: true },
			{ key: 'min', label: 'Min', numeric: true },
			{ key: 'q1', label: 'Q1', numeric: true },
			{ key: 'median', label: 'Median', numeric: true },
			{ key: 'q3', label: 'Q3', numeric: true },
			{ key: 'max', label: 'Max', numeric: true }
		],
		rows: boxes.map((b) => ({ ...b }))
	});
</script>

{#if boxes.length === 0}
	<p class="py-10 text-center text-sm text-muted-foreground">No numeric data for this column.</p>
{:else}
	<PlotFigure title={caption.title} subtitle={caption.subtitle} {draw} {table} bind:handle />
{/if}
