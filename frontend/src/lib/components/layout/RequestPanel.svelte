<script lang="ts">
	import type { Snippet } from 'svelte';
	import { fetchDatasetsForFeatures } from '#lib/api.js';
	import { knownCoverage, rememberCoverage } from '#lib/stores/coverageCounts.js';
	import CoverageStatus from '#lib/components/map/CoverageStatus.svelte';
	import { goto } from '$app/navigation';
	import { ArrowRight, Pencil } from '@lucide/svelte';
	import { selection, selectionFcIds, selectionSummary, customizeHref } from '#lib/stores/selection.js';
	import { customBoundary } from '#lib/stores/customBoundary.js';
	import { cart, cartCount } from '#lib/stores/cart.js';
	import { entryColumns } from '#lib/utils/outputColumns.js';
	import type { Step } from '#lib/stores/ui.js';
	import ShareLinkButton from '#lib/components/ShareLinkButton.svelte';
	import { currentRecipe } from '#lib/recipe.js';

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
		/**
		 * The body is a flex column (gap-3), so a part of it given a minimum
		 * height can shrink and scroll on its own before the whole body does
		 */
		fill?: boolean;
		/**
		 * Added after a collapsed step's summary. Customize Datasets gets the
		 * stored selection's dataset count unless the page gives its own (the
		 * map page counts its working selection as it changes).
		 */
		notes?: Partial<Record<Step, Snippet>>;
	}

	let { active, children, actions, bare = false, fill = false, notes = {} }: Props = $props();

	// How many datasets cover the stored selection, for the Customize Datasets
	// summary on pages that don't count it themselves: the count the map or
	// Customize page found, or asked for here if neither has (a reload on
	// Review). Not for a custom upload, whose coverage isn't recorded.
	let coverageCount = $state<number | null>(null);
	let coverageLoading = $state(false);
	let coverageError = $state(false);
	const countsOwnCoverage = $derived(active === 'search' || !!notes.search);

	$effect(() => {
		const ids = $selection && !$customBoundary.active ? $selection.resolvedFeatureIds : [];
		coverageError = false;
		if (countsOwnCoverage || ids.length === 0) {
			coverageCount = null;
			coverageLoading = false;
			return;
		}
		const known = knownCoverage(ids);
		if (known !== undefined) {
			coverageCount = known;
			coverageLoading = false;
			return;
		}
		let cancelled = false;
		coverageLoading = true;
		fetchDatasetsForFeatures(ids)
			.then((datasets) => {
				rememberCoverage(ids, datasets.length);
				if (!cancelled) coverageCount = datasets.length;
			})
			.catch(() => {
				if (!cancelled) {
					coverageCount = null;
					coverageError = true;
				}
			})
			.finally(() => {
				if (!cancelled) coverageLoading = false;
			});
		return () => {
			cancelled = true;
		};
	});

	const stepNotes = $derived<Partial<Record<Step, Snippet>>>(
		!countsOwnCoverage && (coverageLoading || coverageError || coverageCount !== null)
			? { ...notes, search: storedCoverage }
			: notes
	);

	// Shown wherever feature counts first appear, for readers new to GIS terms
	const FEATURE_DEFINITION = 'A feature is one area in a boundary set, such as a single district in Ghana ADM2.';

	// A summary is text and counts, so the counts can be set in bold (and digits
	// in a name, like a boundary's "ADM2", aren't)
	type Part = string | { count: number };

	const plural = (n: number, word: string): Part[] => [{ count: n }, ` ${word}${n === 1 ? '' : 's'}`];

	// "X features across Y boundary sets selected"; the boundary name until the
	// feature count has resolved.
	const boundaryLabel = $derived.by((): Part[] | null => {
		if ($customBoundary.saved && $customBoundary.active) {
			const n = $customBoundary.featureCount;
			return n
				? [...plural(n, 'feature'), ' in a custom boundary']
				: [$customBoundary.fileName || 'Custom boundary'];
		}
		if (!$selection) return null;
		const features = $selection.resolvedFeatureIds.length;
		const sets = $selectionFcIds.length;
		if (features > 0) return [...plural(features, 'feature'), ' across ', ...plural(sets, 'boundary set'), ' selected'];
		return $selectionSummary?.label ? [$selectionSummary.label] : null;
	});

	// "Copy share link" (GEO-126), on every step once boundaries are chosen.
	// A custom upload can't be shared, so the button says why instead.
	const customInUse = $derived($customBoundary.active && !!$customBoundary.finalFeatures);
	// Changes whenever the shareable request does, so the share button can tell
	// a copied link has gone out of date.
	const recipeKey = $derived.by(() => {
		void $selection;
		void $cart;
		return JSON.stringify(currentRecipe());
	});
	const showShare = $derived(customInUse || (!!$selection && !$customBoundary.active));

	const totalColumns = $derived($cart.reduce((n, item) => n + entryColumns(item), 0));

	type Section = {
		id: Step;
		title: string;
		href: string | null;
		/** Second line of the collapsed header */
		summary: Part[];
		/** Why a collapsed header can't be clicked yet */
		blocked: string;
	};

	const sections = $derived<Section[]>([
		{
			id: 'map',
			title: '1. Select Boundaries',
			href: '/',
			summary: boundaryLabel ?? ['No boundary sets selected'],
			blocked: ''
		},
		{
			id: 'search',
			title: '2. Customize Datasets',
			href: $customizeHref,
			// Every entry counts, so two versions of one dataset are two selections
			summary:
				$cart.length > 0
					? [...plural(totalColumns, 'column'), ' across ', ...plural($cart.length, 'dataset selection')]
					: ['No datasets added yet'],
			blocked: 'Select boundaries first'
		},
		{
			id: 'review',
			title: '3. Review & Submit',
			href: $cartCount > 0 ? '/review' : null,
			summary: [],
			blocked: 'Add a dataset first'
		}
	]);
</script>

{#snippet storedCoverage()}
	<CoverageStatus loading={coverageLoading} count={coverageCount} error={coverageError} inline />
{/snippet}

<!-- Full width on narrow screens, where it takes turns with the main area (layout.css) -->
<nav
	aria-label="Request steps"
	class="request-panel relative flex h-full w-full shrink-0 flex-col overflow-hidden bg-card md:w-[28rem] md:max-w-[45vw] md:border-r"
>
	{#each sections as s (s.id)}
		{#if s.id === active}
			<section
				aria-labelledby="panel-{s.id}"
				class="flex min-h-0 flex-1 flex-col border-b last:border-b-0"
				style:view-transition-name="panel-{s.id}"
			>
				<div class="flex items-center justify-between gap-2 px-4 pt-4 {bare ? 'pb-1' : 'pb-2'}">
					<!-- The page's one top-level heading on each request step -->
					<h1 id="panel-{s.id}" class="text-h4 text-foreground" aria-current="step">{s.title}</h1>
					{@render actions?.()}
				</div>
				<div
					class={bare
						? 'flex min-h-0 flex-1 flex-col'
						: `relative min-h-0 flex-1 overflow-y-auto px-4 pb-4 pt-1 ${fill ? 'flex flex-col gap-3' : ''}`}
				>
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
					{#if s.summary.length > 0 || stepNotes[s.id]}
						{@const note = stepNotes[s.id]}
						<span
							class="block truncate text-xs text-muted-foreground"
							title={s.id === 'map' ? FEATURE_DEFINITION : undefined}
							>{#each s.summary as part, i (i)}{#if typeof part === 'string'}{part}{:else}<strong>{part.count.toLocaleString()}</strong>{/if}{/each}{#if note}{#if s.summary.length > 0}<span class="mx-1.5" aria-hidden="true">·</span>{/if}{@render note()}{/if}</span
						>
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
	{#if showShare}
		<div class="border-t px-4 py-2">
			<ShareLinkButton
				getRecipe={currentRecipe}
				current={recipeKey}
				unavailable={customInUse ? "Requests with a custom upload can't be shared." : null}
			/>
		</div>
	{/if}
</nav>
