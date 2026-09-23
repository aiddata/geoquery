<script lang="ts">
	import type { StatsPoint } from '$lib/api';

	interface Props {
		data: StatsPoint[];
		color?: string;
		label?: string;
	}

	// Rendered as inline SVG rather than with a charting library: the series is a
	// flat list of date/count pairs, so a dependency (and the rebuild it forces)
	// buys nothing here.
	let { data, color = 'var(--color-primary)', label = 'items' }: Props = $props();

	let max = $derived(Math.max(1, ...data.map((d) => d.count)));
	let hovered = $state<number | null>(null);

	// Enough gaps that labels stay legible at any series length.
	let labelEvery = $derived(Math.max(1, Math.ceil(data.length / 12)));

	const fmt = (n: number) => n.toLocaleString();
</script>

{#if data.length === 0}
	<div class="flex h-72 items-center justify-center text-sm text-muted-foreground">
		No data for this selection.
	</div>
{:else}
	<div class="relative">
		<div class="flex h-72 items-end gap-px" role="img" aria-label="{label} over time">
			{#each data as point, i (point.date)}
				<div
					class="group relative flex flex-1 items-end"
					style="height: 100%"
					onmouseenter={() => (hovered = i)}
					onmouseleave={() => (hovered = null)}
					role="presentation"
				>
					<div
						class="w-full rounded-t-sm transition-opacity"
						style="height: {(point.count / max) * 100}%; background-color: {color}; opacity: {hovered ===
							null || hovered === i
							? 1
							: 0.45}; min-height: {point.count > 0 ? '2px' : '0'}"
					></div>

					{#if hovered === i}
						<div
							class="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 -translate-x-1/2 whitespace-nowrap rounded-md border bg-popover px-2 py-1 text-xs shadow-md"
						>
							<div class="font-medium">{point.date}</div>
							<div class="text-muted-foreground">{fmt(point.count)} {label}</div>
						</div>
					{/if}
				</div>
			{/each}
		</div>

		<div class="mt-2 flex gap-px text-[10px] text-muted-foreground">
			{#each data as point, i (point.date)}
				<div class="flex-1 overflow-hidden text-center">
					{#if i % labelEvery === 0}
						<span class="inline-block origin-center -rotate-45 whitespace-nowrap">
							{point.date}
						</span>
					{/if}
				</div>
			{/each}
		</div>
	</div>
{/if}
