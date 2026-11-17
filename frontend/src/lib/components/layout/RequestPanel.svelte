<script lang="ts">
	import type { Snippet } from 'svelte';
	import { goto } from '$app/navigation';
	import { ArrowRight, Pencil } from '@lucide/svelte';
	import { selection, selectionFcIds, selectionSummary, customizeHref } from '#lib/stores/selection.js';
	import { customBoundary } from '#lib/stores/customBoundary.js';
	import { cart, cartCount } from '#lib/stores/cart.js';
	import { entryColumns } from '#lib/utils/outputColumns.js';
	import type { Step } from '#lib/stores/ui.js';

	// The request's three steps as one docked column, the same on every step
	// page: the current step's section is expanded (its page passes the body),
	// the others are one-line headers that navigate to their step once it can
	// be reached.
	interface Props {
		active: Step;
		children: Snippet;
		/** Controls at the right of the expanded section's header, e.g. Restart */
		actions?: Snippet;
		/** The body brings its own padding and scrolling (e.g. the dataset list) */
		bare?: boolean;
	}

	let { active, children, actions, bare = false }: Props = $props();

	const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;

	// "X features across Y boundary sets selected"; the boundary name until the
	// feature count has resolved.
	const boundaryLabel = $derived.by(() => {
		if ($customBoundary.saved && $customBoundary.active) {
			const n = $customBoundary.featureCount;
			return n ? `${plural(n, 'feature')} in a custom boundary` : $customBoundary.fileName || 'Custom boundary';
		}
		if (!$selection) return null;
		const features = $selection.resolvedFeatureIds.length;
		const sets = $selectionFcIds.length;
		return features > 0
			? `${plural(features, 'feature')} across ${sets === 1 ? '1 boundary set' : `${sets} boundary sets`} selected`
			: ($selectionSummary?.label ?? null);
	});

	const totalColumns = $derived($cart.reduce((n, item) => n + entryColumns(item), 0));

	type Section = {
		id: Step;
		title: string;
		href: string | null;
		/** Second line of the collapsed header */
		summary: string;
		/** Why a collapsed header can't be clicked yet */
		blocked: string;
	};

	const sections = $derived<Section[]>([
		{
			id: 'map',
			title: '1. Select Boundaries',
			href: '/',
			summary: boundaryLabel ?? 'No boundary sets selected',
			blocked: ''
		},
		{
			id: 'search',
			title: '2. Customize Datasets',
			href: $customizeHref,
			// Every entry counts, so two versions of one dataset are two selections
			summary:
				$cart.length > 0
					? `${plural(totalColumns, 'column')} across ${plural($cart.length, 'dataset selection')}`
					: 'No datasets added yet',
			blocked: 'Select boundaries first'
		},
		{
			id: 'review',
			title: '3. Review & Submit',
			href: $cartCount > 0 ? '/review' : null,
			summary: '',
			blocked: 'Add a dataset first'
		}
	]);
</script>

<!-- Full width on narrow screens, where it takes turns with the main area (layout.css) -->
<nav
	aria-label="Request steps"
	class="request-panel flex h-full w-full shrink-0 flex-col overflow-hidden bg-card md:w-[28rem] md:max-w-[45vw] md:border-r"
>
	{#each sections as s (s.id)}
		{#if s.id === active}
			<section
				aria-labelledby="panel-{s.id}"
				class="flex min-h-0 flex-1 flex-col border-b last:border-b-0"
				style:view-transition-name="panel-{s.id}"
			>
				<div class="flex items-center justify-between gap-2 px-4 pt-4 {bare ? 'pb-1' : 'pb-2'}">
					<h2 id="panel-{s.id}" class="text-h4 text-foreground" aria-current="step">{s.title}</h2>
					{@render actions?.()}
				</div>
				<div class={bare ? 'flex min-h-0 flex-1 flex-col' : 'min-h-0 flex-1 overflow-y-auto px-4 pb-4'}>
					{@render children()}
				</div>
			</section>
		{:else if s.href}
			<button
				type="button"
				onclick={() => goto(s.href!)}
				style:view-transition-name="panel-{s.id}"
				class="group flex w-full items-center justify-between gap-3 border-b px-4 py-2 text-left transition-colors last:border-b-0 hover:bg-accent focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
			>
				<span class="min-w-0">
					<span class="block font-heading text-h4 font-bold text-foreground">{s.title}</span>
					{#if s.summary}
						<span class="block truncate text-xs text-muted-foreground">{s.summary}</span>
					{/if}
				</span>
				{#if s.id === 'review'}
					<!-- Moving on is the step page's own button (Continue to Review);
					     the header goes there too, but quietly. -->
					<ArrowRight class="size-4 shrink-0 text-muted-foreground group-hover:text-foreground" aria-hidden="true" />
				{:else}
					<Pencil class="size-4 shrink-0 text-muted-foreground group-hover:text-foreground" aria-hidden="true" />
				{/if}
			</button>
		{:else}
			<div
				class="flex cursor-not-allowed items-center justify-between gap-3 border-b px-4 py-2 last:border-b-0"
				aria-disabled="true"
				title={s.blocked}
				style:view-transition-name="panel-{s.id}"
			>
				<span class="min-w-0 font-heading text-h4 font-bold text-muted-foreground/60">{s.title}</span>
			</div>
		{/if}
	{/each}
</nav>
