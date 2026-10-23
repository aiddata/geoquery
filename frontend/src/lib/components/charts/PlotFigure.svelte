<script lang="ts" module>
	/** What the chart panel needs to export a drawn chart as an image. */
	export interface FigureHandle {
		plot: SVGSVGElement | HTMLElement;
		title: string;
		subtitle?: string;
	}
</script>

<script lang="ts">
	import { onMount, type Snippet } from 'svelte';
	import { loadPlot, type DrawFn, type PlotModule } from '$lib/charts/plot';
	import { tokenScheme } from '$lib/stores/theme';
	import { readTokens } from '$lib/theme/tokens';
	import ChartTable, { type ChartTableData } from './ChartTable.svelte';

	interface Props {
		title: string;
		/** Hide the caption visually (still read by screen readers) when the surrounding card already titles the chart */
		titleHidden?: boolean;
		subtitle?: string;
		/** A note under the chart, e.g. how many features a line chart draws */
		caption?: string;
		/** Builds the plot; runs again when anything it reads, the theme, contrast mode or width changes */
		draw: DrawFn;
		table: ChartTableData;
		handle?: FigureHandle | null;
		/** Controls drawn between the caption and the chart, outside the exported image */
		controls?: Snippet;
	}

	let {
		title,
		titleHidden = false,
		subtitle,
		caption,
		draw,
		table,
		handle = $bindable(),
		controls
	}: Props = $props();

	const id = $props.id();

	let frame: HTMLDivElement;
	let width = $state(0);
	let Plot = $state<PlotModule | null>(null);

	onMount(() => {
		loadPlot().then((m) => (Plot = m));
		// Plot draws at a fixed width, so redraw when the frame resizes. A hidden frame
		// (the charts tab behind the map) measures 0 and is skipped until it's shown.
		const observer = new ResizeObserver(() => {
			const w = frame.clientWidth;
			if (Math.abs(w - width) > 4) width = w;
		});
		observer.observe(frame);
		return () => observer.disconnect();
	});

	$effect(() => {
		void $tokenScheme; // theme or contrast mode changed: tokens resolve differently
		if (!Plot || width === 0) return;
		const plot = draw({ Plot, t: readTokens(), width });
		frame.replaceChildren(plot);
		handle = { plot, title, subtitle };
	});
</script>

<figure aria-labelledby="{id}-title" class="space-y-3">
	<figcaption class={titleHidden ? 'sr-only' : undefined}>
		<span id="{id}-title" class="block font-heading text-h4 font-bold">{title}</span>
		{#if subtitle}<span class="block text-sm text-muted-foreground">{subtitle}</span>{/if}
	</figcaption>

	{@render controls?.()}

	<div bind:this={frame} class="aid-plot w-full"></div>

	{#if caption}<p class="text-sm text-muted-foreground">{caption}</p>{/if}

	<details class="text-sm">
		<summary class="cursor-pointer font-bold text-link hover:text-link-hover">Show the numbers</summary>
		<div class="mt-2">
			<ChartTable columns={table.columns} rows={table.rows} />
		</div>
	</details>
</figure>
