<!--
	The selected boundary sets, as a key to the map: each row's glyph is drawn
	the way the map draws that set (its color as an outline on a forest casing,
	the same faint fill, the same line weight by admin level). Clicking a row
	zooms the map to it; hovering or focusing it highlights it on the map.
-->
<script lang="ts" module>
	export interface LegendItem {
		id: number;
		title: string;
		/** A CSS color or `var(--token)`, as the map uses it. */
		color: string;
		/** The map's line width for this set, in px. */
		lineWidth: number;
		level: number | null;
		source: string | null;
		/** The set's group (its country, for geoBoundaries), for the grouped layout. */
		group: string | null;
	}

	/**
	 * Layouts under evaluation (GEO-101): `rows` is what the app uses; the
	 * others are shown on /dev/palette for comparison.
	 */
	export type LegendVariant = 'rows' | 'grouped' | 'compact';
</script>

<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { X } from '@lucide/svelte';

	interface Props {
		items: LegendItem[];
		variant?: LegendVariant;
		onZoom?: (id: number) => void;
		onRemove?: (id: number) => void;
		/** The set to highlight on the map, or null to clear it. */
		onHighlight?: (id: number | null) => void;
	}

	let { items, variant = 'rows', onZoom, onRemove, onHighlight }: Props = $props();

	const uid = $props.id();

	const levelLabel = (item: LegendItem) => (item.level === null ? null : `ADM${item.level}`);
	const meta = (item: LegendItem) => [levelLabel(item), item.source].filter(Boolean).join(' · ');

	// In order of first appearance, so groups don't jump around as sets are added
	let groups = $derived.by(() => {
		const byGroup = new Map<string, LegendItem[]>();
		for (const item of items) {
			const key = item.group ?? 'Other';
			byGroup.set(key, [...(byGroup.get(key) ?? []), item]);
		}
		return [...byGroup];
	});

	function remove(id: number) {
		onHighlight?.(null);
		onRemove?.(id);
	}

	// The casing is 2px wider than the line, as on the map
	const CASING_EXTRA = 2;
</script>

{#snippet glyph(item: LegendItem)}
	<svg viewBox="0 0 20 20" class="size-5 shrink-0" aria-hidden="true">
		<rect x="3" y="3" width="14" height="14" rx="2" style="fill: {item.color}; fill-opacity: 0.15" />
		<rect
			x="3"
			y="3"
			width="14"
			height="14"
			rx="2"
			fill="none"
			style="stroke: var(--forest); stroke-width: {item.lineWidth + CASING_EXTRA}px"
		/>
		<rect
			x="3"
			y="3"
			width="14"
			height="14"
			rx="2"
			fill="none"
			style="stroke: {item.color}; stroke-width: {item.lineWidth}px"
		/>
	</svg>
{/snippet}

{#snippet row(item: LegendItem)}
	{@const compact = variant === 'compact'}
	<li class="flex items-center gap-1 {compact ? 'py-0.5' : 'py-1'}">
		<button
			type="button"
			class="flex min-w-0 flex-1 items-center gap-2.5 rounded-md px-2 text-left transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring
				{compact ? 'py-1' : 'py-1.5'}"
			title="Zoom the map to this boundary set"
			onclick={() => onZoom?.(item.id)}
			onpointerenter={() => onHighlight?.(item.id)}
			onpointerleave={() => onHighlight?.(null)}
			onfocus={() => onHighlight?.(item.id)}
			onblur={() => onHighlight?.(null)}
		>
			{@render glyph(item)}
			<span class="sr-only">Zoom to</span>
			{#if compact}
				<span class="min-w-0 flex-1 truncate text-sm font-bold">{item.title}</span>
				{#if levelLabel(item)}
					<span class="shrink-0 text-xs tabular-nums text-muted-foreground">{levelLabel(item)}</span>
				{/if}
			{:else}
				<span class="min-w-0 flex-1">
					<span class="block text-sm font-bold leading-snug">{item.title}</span>
					{#if meta(item)}
						<span class="mt-px block text-xs text-muted-foreground">{meta(item)}</span>
					{/if}
				</span>
			{/if}
		</button>
		<Button
			variant="ghost"
			size="icon-sm"
			class="shrink-0 text-muted-foreground hover:text-foreground"
			onclick={() => remove(item.id)}
			aria-label="Remove {item.title}"
		>
			<X class="size-4" />
		</Button>
	</li>
{/snippet}

<section aria-labelledby="{uid}-heading" class="space-y-1">
	<div class="flex items-baseline justify-between gap-2">
		<h2 id="{uid}-heading" class="text-sm font-bold text-foreground">Your Selections</h2>
		<span class="text-xs tabular-nums text-muted-foreground">
			{items.length} boundary set{items.length === 1 ? '' : 's'}
		</span>
	</div>
	{#if variant === 'grouped'}
		<div class="space-y-2">
			{#each groups as [group, members] (group)}
				<div>
					<h3 class="border-b px-2 pb-1 pt-1.5 text-xs font-bold text-muted-foreground">{group}</h3>
					<ul class="divide-y">
						{#each members as item (item.id)}{@render row(item)}{/each}
					</ul>
				</div>
			{/each}
		</div>
	{:else}
		<ul class="divide-y border-y">
			{#each items as item (item.id)}{@render row(item)}{/each}
		</ul>
	{/if}
</section>
