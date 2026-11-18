<script lang="ts">
	import { Input } from '#lib/components/ui/input/index.js';
	import ClearSearchButton from '#lib/components/ClearSearchButton.svelte';
	import * as Select from '#lib/components/ui/select/index.js';
	import * as Card from '#lib/components/ui/card/index.js';
	import { ScrollArea } from '#lib/components/ui/scroll-area/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';
	import { Search, ArrowDownWideNarrow, ArrowUpNarrowWide, CircleAlert } from '@lucide/svelte';
	import type { DatasetSummary, DatasetCategory } from '#lib/api.js';
	import CoverageChip from './CoverageChip.svelte';
	import CoveragePie from './CoveragePie.svelte';

	interface Props {
		datasets: DatasetSummary[];
		categories: DatasetCategory[];
		selectedDataset: DatasetSummary | null;
		onSelect: (dataset: DatasetSummary) => void;
		outOfRangeNames?: Set<string>;
		/** Feature datasets whose current filters aren't in the request; marked with an exclamation. */
		unsavedNames?: Set<string>;
		/** Columns each dataset adds to the output, across its entries in the request */
		columnCounts?: Map<string, number>;
		/**
		 * The selected boundary sets, when there are several: datasets covering
		 * only some of them get a coverage chip, and the list can sort by it.
		 */
		boundarySets?: { id: number; title: string }[];
	}

	let {
		datasets,
		categories,
		selectedDataset,
		onSelect,
		outOfRangeNames = new Set(),
		unsavedNames = new Set(),
		columnCounts = new Map(),
		boundarySets = []
	}: Props = $props();

	let searchText = $state('');
	let searchInput = $state<HTMLInputElement | null>(null);
	let selectedCategory = $state('all');
	type SortField = 'title' | 'coverage' | 'date_updated';
	const SORT_LABELS: Record<SortField, string> = { title: 'Name', coverage: 'Coverage', date_updated: 'Date updated' };
	// Each field's natural order: A to Z, most coverage first, newest first
	const NATURAL_ASC: Record<SortField, boolean> = { title: true, coverage: false, date_updated: false };
	const DIRECTION: Record<SortField, [asc: string, desc: string]> = {
		title: ['A to Z', 'Z to A'],
		coverage: ['least coverage first', 'most coverage first'],
		date_updated: ['oldest first', 'newest first']
	};
	let sortField = $state<SortField>('title');
	let sortAsc = $state(true);

	/** How many of the selected boundary sets a dataset covers (all, when not reported). */
	function coveredCount(d: DatasetSummary): number {
		return d.covered_boundary_sets?.length ?? boundarySets.length;
	}
	const isPartial = (d: DatasetSummary) =>
		boundarySets.length > 1 && !!d.covered_boundary_sets && d.covered_boundary_sets.length < boundarySets.length;
	// Coverage sorting only does something when some dataset is partial
	const anyPartial = $derived(datasets.some(isPartial));
	const sortFields = $derived<SortField[]>(anyPartial ? ['title', 'coverage', 'date_updated'] : ['title', 'date_updated']);
	const activeSort = $derived<SortField>(sortFields.includes(sortField) ? sortField : 'title');
	const activeAsc = $derived(activeSort === sortField ? sortAsc : NATURAL_ASC.title);
	const directionLabel = $derived(DIRECTION[activeSort][activeAsc ? 0 : 1]);

	function setSort(field: SortField) {
		sortField = field;
		sortAsc = NATURAL_ASC[field];
	}

	let filteredDatasets = $derived.by(() => {
		let result = datasets;

		// Filter by category: any of the category's tags (settings.DATASET_CATEGORIES)
		if (selectedCategory !== 'all') {
			const wanted = new Set(categories.find((c) => c.tag === selectedCategory)?.tags ?? []);
			result = result.filter((d) => d.tags?.some((t) => wanted.has(t.toLowerCase())));
		}

		// Filter by search text
		if (searchText.trim()) {
			const q = searchText.toLowerCase();
			result = result.filter(
				(d) =>
					(d.title ?? d.name).toLowerCase().includes(q) ||
					d.tags?.some((t) => t.toLowerCase().includes(q))
			);
		}

		// Sort; ties in coverage or date fall back to name, A to Z
		const byName = (a: DatasetSummary, b: DatasetSummary) => (a.title ?? a.name).localeCompare(b.title ?? b.name);
		result = [...result].sort((a, b) => {
			let cmp: number;
			if (activeSort === 'date_updated') {
				cmp = (a.date_updated ?? '').localeCompare(b.date_updated ?? '');
			} else if (activeSort === 'coverage') {
				cmp = coveredCount(a) - coveredCount(b);
			} else {
				return activeAsc ? byName(a, b) : byName(b, a);
			}
			return (activeAsc ? cmp : -cmp) || byName(a, b);
		});

		return result;
	});

</script>

<div class="flex h-full flex-col">
	<!-- Category, search and sort, kept compact to leave room for the list -->
	<div class="space-y-2 border-b px-4 pb-3 pt-1">
		<Select.Root type="single" bind:value={selectedCategory}>
			<Select.Trigger class="h-8 w-full text-sm" aria-label="Dataset category">
				{selectedCategory === 'all'
					? 'All Categories'
					: categories.find((c) => c.tag === selectedCategory)?.display ?? selectedCategory}
			</Select.Trigger>
			<Select.Content>
				<Select.Item value="all" label="All Categories" />
				{#each categories as cat}
					<Select.Item value={cat.tag} label={cat.display} />
				{/each}
			</Select.Content>
		</Select.Root>

		<!-- Search -->
		<div class="relative">
			<Search class="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
			<Input
				bind:ref={searchInput}
				bind:value={searchText}
				placeholder="Search datasets..."
				aria-label="Search datasets"
				class="h-8 pl-8 pr-8 text-sm"
			/>
			<ClearSearchButton
				value={searchText}
				onClear={() => {
					searchText = '';
					searchInput?.focus();
				}}
			/>
		</div>

		<!-- Sort: a field, and a button that reverses its order -->
		<div class="flex items-center gap-1 text-xs">
			<span class="mr-1 text-muted-foreground">Sort by</span>
			<Select.Root type="single" value={activeSort} onValueChange={(v) => setSort(v as SortField)}>
				<Select.Trigger size="sm" class="h-7 gap-1 px-2 text-xs" aria-label="Sort datasets by">
					{SORT_LABELS[activeSort]}
				</Select.Trigger>
				<Select.Content>
					{#each sortFields as field (field)}
						<Select.Item value={field} label={SORT_LABELS[field]} class="text-xs" />
					{/each}
				</Select.Content>
			</Select.Root>
			<Tooltip.Root>
				<Tooltip.Trigger>
					{#snippet child({ props })}
						<Button
							{...props}
							variant="ghost"
							size="icon-sm"
							class="size-7 text-muted-foreground"
							aria-label="Sorted {directionLabel}. Reverse the order"
							onclick={() => {
								sortField = activeSort;
								sortAsc = !activeAsc;
							}}
						>
							{#if activeAsc}<ArrowUpNarrowWide class="size-3.5" />{:else}<ArrowDownWideNarrow class="size-3.5" />{/if}
						</Button>
					{/snippet}
				</Tooltip.Trigger>
				<Tooltip.Content>Sorted {directionLabel}</Tooltip.Content>
			</Tooltip.Root>
			<span class="ml-auto tabular-nums text-muted-foreground" aria-live="polite">
				{filteredDatasets.length} of {datasets.length} datasets
			</span>
		</div>
		{#if anyPartial}
			<p class="flex items-center gap-1.5 text-xs text-muted-foreground">
				<CoveragePie fraction={0.5} class="size-3 shrink-0" />
				Covers only some of your selected boundary sets
			</p>
		{/if}
	</div>

	<!-- Dataset list -->
	<ScrollArea class="min-h-0 flex-1">
		<div class="space-y-1 p-2">
			{#if filteredDatasets.length === 0}
				<p class="px-4 py-8 text-center text-sm text-muted-foreground">No datasets found.</p>
			{:else}
				{#each filteredDatasets as dataset}
					{@const partial = isPartial(dataset)}
					<!-- The whole row selects; the selected dataset's metadata is in
					     the centre panel. The coverage chip sits over the row's top
					     right, outside the button, so it can have its own tooltip. -->
					<div class="relative">
					<button
						type="button"
						class="block w-full cursor-pointer rounded-md px-3 py-2.5 text-left transition-colors
							{selectedDataset?.name === dataset.name
							? 'bg-primary/10 text-primary'
							: 'hover:bg-muted'}"
						aria-pressed={selectedDataset?.name === dataset.name}
						onclick={() => onSelect(dataset)}
					>
						<p class="flex items-start gap-2 text-sm font-bold leading-snug {partial ? 'pr-6' : ''}">
							<span class="min-w-0 flex-1">{dataset.title ?? dataset.name}</span>
							{#if unsavedNames.has(dataset.name)}
								<CircleAlert
									class="mt-0.5 size-4 shrink-0 text-warning-text"
									aria-hidden="true"
								/>
								<span class="sr-only">(filters not added to your request yet)</span>
							{/if}
							{#if partial}
								<span class="sr-only">(covers {coveredCount(dataset)} of {boundarySets.length} selected boundary sets)</span>
							{/if}
						</p>
						<!-- Raster / Feature is in the dataset's metadata (More metadata); this line only
						     appears for an out-of-range flag or a column count -->
						{#if outOfRangeNames.has(dataset.name) || columnCounts.get(dataset.name)}
						<div class="mt-px flex items-center gap-1.5">
							{#if outOfRangeNames.has(dataset.name)}
								<Badge variant="warning">out of range</Badge>
							{/if}
							{#if columnCounts.get(dataset.name)}
								{@const cols = columnCounts.get(dataset.name)!}
								<!-- Bottom right: what this dataset adds to the output (its mark of being in the request) -->
								<span class="ml-auto text-xs tabular-nums text-muted-foreground">
									{cols.toLocaleString()} column{cols === 1 ? '' : 's'}<span class="sr-only"> in your request</span>
								</span>
							{/if}
						</div>
						{/if}
					</button>
					{#if partial}
						<div class="absolute right-2 top-2">
							<CoverageChip sets={boundarySets} covered={dataset.covered_boundary_sets ?? []} />
						</div>
					{/if}
					</div>
				{/each}
			{/if}
		</div>
	</ScrollArea>
</div>
