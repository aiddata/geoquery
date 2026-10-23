<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import type { SingleColCard } from '../chartTypes';
	import { columnValues, fmt } from '$lib/viz';
	import { aidBase, aidTip, niceScale, tickFormatFor, type DrawFn } from '$lib/charts/plot';
	import { columnCaption } from '$lib/charts/labels';
	import PlotFigure, { type FigureHandle } from '$lib/components/charts/PlotFigure.svelte';

	interface Props {
		data: VizPayload;
		card: SingleColCard;
		handle?: FigureHandle | null;
	}
	let { data, card, handle = $bindable() }: Props = $props();

	const N_BINS = 20;

	interface Bin {
		lo: number;
		hi: number;
		count: number;
	}

	function makeBins(vals: number[]): Bin[] {
		if (!vals.length) return [];
		let min = vals[0],
			max = vals[0];
		for (const v of vals) {
			if (v < min) min = v;
			if (v > max) max = v;
		}
		if (min === max) return [{ lo: min, hi: max, count: vals.length }];
		const w = (max - min) / N_BINS;
		const bins: Bin[] = Array.from({ length: N_BINS }, (_, i) => ({
			lo: min + i * w,
			hi: min + (i + 1) * w,
			count: 0
		}));
		for (const v of vals) bins[Math.min(Math.floor((v - min) / w), N_BINS - 1)].count++;
		return bins;
	}

	let vals = $derived(columnValues(data, card.column));
	let bins = $derived(makeBins(vals));
	let mean = $derived(vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0);
	let caption = $derived(columnCaption(data, card.column, 'Distribution'));

	const draw: DrawFn = ({ Plot, t, width }) => {
		const lo = bins[0].lo;
		const hi = bins[bins.length - 1].hi;
		// A single-value column draws one bar with some room either side
		const singleValue = lo === hi;
		const x = niceScale(lo, hi, width < 420 ? 4 : 6);
		const maxCount = Math.max(...bins.map((b) => b.count));
		const y = niceScale(0, maxCount, 4);
		const tallest = bins.reduce((a, b) => (b.count > a.count ? b : a));
		const rects = singleValue
			? [{ ...bins[0], lo: x.domain[0] + (x.domain[1] - x.domain[0]) * 0.45, hi: x.domain[0] + (x.domain[1] - x.domain[0]) * 0.55 }]
			: bins;

		return Plot.plot({
			...aidBase(t, width, 240),
			marginTop: 26,
			marginLeft: 48,
			marginRight: 16,
			ariaLabel: `Distribution of ${caption.title}, ${caption.subtitle}`,
			ariaDescription: `${vals.length.toLocaleString()} values from ${fmt(lo)} to ${fmt(hi)}, mean ${fmt(mean)}. The most common range is ${fmt(tallest.lo)} to ${fmt(tallest.hi)}, with ${tallest.count.toLocaleString()} features.`,
			x: { domain: x.domain, ticks: x.ticks, tickFormat: tickFormatFor(x.ticks), tickSize: 0, label: null },
			y: { domain: y.domain, ticks: y.ticks, tickFormat: tickFormatFor(y.ticks), tickSize: 0, label: 'Features', labelArrow: 'none' },
			marks: [
				Plot.gridY(y.ticks.slice(1), { stroke: t.grid, strokeOpacity: 1 }),
				// Bins are contiguous, so they're separated by 1px rather than capped at 24px (§11)
				Plot.rectY(rects, { x1: 'lo', x2: 'hi', y: 'count', fill: t.series[0], stroke: t.edge, strokeWidth: 1, inset: 0.5 }),
				Plot.ruleY([0], { stroke: t.axis }),
				// Reference line: dashed foreground with a direct label, not red (§11)
				Plot.ruleX([mean], { stroke: t.foreground, strokeWidth: 1.5, strokeDasharray: '4,3' }),
				Plot.text([mean], {
					x: (d: number) => d,
					frameAnchor: 'top',
					dy: -16,
					dx: 4,
					textAnchor: 'start',
					text: (d: number) => `Mean ${fmt(d)}`,
					fill: t.foreground,
					fontWeight: 700
				}),
				Plot.tip(
					rects,
					Plot.pointerX({
						x1: 'lo',
						x2: 'hi',
						y: 'count',
						title: (b: Bin) => `${fmt(b.lo)} – ${fmt(b.hi)}\n${b.count.toLocaleString()} features`,
						...aidTip(t)
					})
				)
			]
		});
	};

	let table = $derived({
		columns: [
			{ key: 'range', label: 'Range' },
			{ key: 'count', label: 'Features', numeric: true }
		],
		rows: bins.map((b) => ({ range: `${fmt(b.lo)} – ${fmt(b.hi)}`, count: b.count }))
	});
</script>

{#if vals.length === 0}
	<p class="py-10 text-center text-sm text-muted-foreground">No numeric data for this column.</p>
{:else}
	<PlotFigure title={caption.title} subtitle={caption.subtitle} {draw} {table} bind:handle />
{/if}
