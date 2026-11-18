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
		/** Hidden on the map from the map's level legend (GEO-141); still selected. */
		hidden?: boolean;
	}

	/**
	 * Layouts under evaluation (GEO-101): `rows` is what the app uses; the
	 * others are shown on /dev/palette for comparison.
	 */
	export type LegendVariant = 'rows' | 'grouped' | 'compact';
</script>

<script lang="ts">
	import { tick, type Snippet } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import { ChevronRight, Info, X } from '@lucide/svelte';

	interface Props {
		items: LegendItem[];
		variant?: LegendVariant;
		onZoom?: (id: number) => void;
		onRemove?: (id: number) => void;
		/** The set to highlight on the map, or null to clear it. */
		onHighlight?: (id: number | null) => void;
		/** About the selection, behind an info button beside the count */
		info?: Snippet;
		/**
		 * Just the header, e.g. while Bulk select is open (it shows the selection
		 * too). The header then opens the list again, through onExpand.
		 */
		collapsed?: boolean;
		onExpand?: () => void;
	}

	let { items, variant = 'rows', onZoom, onRemove, onHighlight, info, collapsed = false, onExpand }: Props = $props();

	const uid = $props.id();

	// A long list scrolls on its own, in a parent column that lets it shrink,
	// but keeps a few rows in view: the section's minimum is the heading, the
	// gap and the list's 7rem, with a little over that the list grows into.
	// One or two rows never shrink. The scroller is positioned (relative) so the
	// rows' absolutely positioned sr-only text is clipped by it, not by the page.
	const scrolls = $derived(items.length > 2 && !collapsed);

	// The header's button goes once the list opens, so focus moves to the heading
	async function expand() {
		onExpand?.();
		await tick();
		document.getElementById(`${uid}-heading`)?.focus();
	}

	const count = $derived(`${items.length} boundary set${items.length === 1 ? '' : 's'}`);

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
	<li class="flex items-center gap-1 {compact ? 'py-0.5' : 'py-1'} {item.hidden ? 'opacity-55' : ''}">
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
			{#if item.hidden}<span class="sr-only">(hidden on the map)</span>{/if}
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

<section
	aria-labelledby="{uid}-heading"
	class="flex flex-col gap-1 {scrolls ? 'min-h-[8.75rem]' : 'shrink-0'}"
>
	<div class="flex shrink-0 items-center justify-between gap-2">
		{#if collapsed}
			<!-- Collapsed: the whole header opens the list; the info button stays its own control -->
			<h2 id="{uid}-heading" class="min-w-0 flex-1 text-sm font-bold text-foreground">
				<button
					type="button"
					class="-ml-1 flex w-full items-center justify-between gap-2 rounded-sm py-0.5 pl-1 text-left hover:text-link focus-visible:outline-2 focus-visible:outline-ring"
					aria-expanded="false"
					aria-controls="{uid}-list"
					onclick={expand}
				>
					<span class="flex items-center gap-1">
						<ChevronRight class="size-3.5 text-muted-foreground" aria-hidden="true" />
						Your Selections
					</span>
					<span class="text-xs font-normal tabular-nums text-muted-foreground">{count}</span>
				</button>
			</h2>
		{:else}
			<h2 id="{uid}-heading" tabindex="-1" class="text-sm font-bold text-foreground outline-none">Your Selections</h2>
		{/if}
		<span class="flex shrink-0 items-center gap-1 text-xs tabular-nums text-muted-foreground">
			{#if !collapsed}{count}{/if}
			{#if info}
				<!-- A popover, not a tooltip: what it says can hold a link -->
				<Popover.Root>
					<Popover.Trigger
						class="inline-flex size-5 items-center justify-center rounded-full text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
						aria-label="About selecting more than one boundary set"
					>
						<Info class="size-3.5" aria-hidden="true" />
					</Popover.Trigger>
					<Popover.Content side="bottom" align="end" class="w-72 p-3 text-xs text-muted-foreground">
						{@render info()}
					</Popover.Content>
				</Popover.Root>
			{/if}
		</span>
	</div>
	{#if collapsed}
		<!-- Nothing: the list is opened from the header -->
	{:else if variant === 'grouped'}
		<div id="{uid}-list" class="space-y-2 {scrolls ? 'relative min-h-28 grow overflow-y-auto' : ''}">
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
		<ul id="{uid}-list" class="divide-y border-y {scrolls ? 'relative min-h-28 grow overflow-y-auto' : ''}">
			{#each items as item (item.id)}{@render row(item)}{/each}
		</ul>
	{/if}
</section>
