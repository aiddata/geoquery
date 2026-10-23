<script lang="ts">
	import { CHOROPLETH_OPACITY } from '$lib/map/choropleth';
	import { fmt, NO_VALUE_COLOR } from '$lib/viz';

	interface Props {
		palette: string[];
		breaks: number[] | null;
	}

	let { palette, breaks }: Props = $props();
</script>

{#if breaks}
	<ul class="space-y-1 font-ui text-xs font-bold tabular-nums" style:--legend-opacity={CHOROPLETH_OPACITY}>
		{#each palette as color, i (i)}
			<li class="flex items-center gap-2">
				<span class="legend-swatch" style:--swatch={color} data-swatch aria-hidden="true"></span>
				<span>{fmt(breaks[i])} – {fmt(breaks[i + 1])}</span>
			</li>
		{/each}
		<li class="flex items-center gap-2">
			<span class="legend-swatch" style:--swatch={NO_VALUE_COLOR} data-swatch aria-hidden="true"></span>
			<span>No data</span>
		</li>
	</ul>
{:else}
	<p class="text-sm text-muted-foreground">No numeric data for this column.</p>
{/if}

<style>
	/* Swatches match the map: the same fill opacity over the surface, with the feature outline */
	.legend-swatch {
		position: relative;
		width: 13px;
		height: 13px;
		flex-shrink: 0;
		border-radius: 2px;
		border: 1px solid var(--chart-edge);
		overflow: hidden;
	}
	.legend-swatch::before {
		content: '';
		position: absolute;
		inset: 0;
		background: var(--swatch);
		opacity: var(--legend-opacity);
	}
</style>
