<script lang="ts">
	import { Input } from '#lib/components/ui/input/index.js';
	import * as Select from '#lib/components/ui/select/index.js';
	import * as Card from '#lib/components/ui/card/index.js';
	import { ScrollArea } from '#lib/components/ui/scroll-area/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import { Search, ArrowUpDown, ChevronDown, ChevronUp, CircleAlert } from '@lucide/svelte';
	import type { DatasetSummary, DatasetCategory } from '#lib/api.js';

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
	}

	let {
		datasets,
		categories,
		selectedDataset,
		onSelect,
		outOfRangeNames = new Set(),
		unsavedNames = new Set(),
		columnCounts = new Map()
	}: Props = $props();

	let searchText = $state('');
	let selectedCategory = $state('all');
	let sortField = $state<'date_updated' | 'title'>('date_updated');
	let sortAsc = $state(false);

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

		// Sort
		result = [...result].sort((a, b) => {
			let cmp: number;
			if (sortField === 'date_updated') {
				cmp = (a.date_updated ?? '').localeCompare(b.date_updated ?? '');
			} else {
				cmp = (a.title ?? a.name).localeCompare(b.title ?? b.name);
			}
			return sortAsc ? cmp : -cmp;
		});

		return result;
	});

</script>

<div class="flex h-full flex-col">
	<!-- Category Filter -->
	<div class="space-y-3 border-b p-4">
		<Select.Root type="single" bind:value={selectedCategory}>
			<Select.Trigger class="w-full">
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
			<Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
			<Input
				bind:value={searchText}
				placeholder="Search datasets..."
				aria-label="Search datasets"
				class="pl-10"
			/>
		</div>

		<!-- Sort controls -->
		<div class="flex items-center gap-2 text-sm">
			<span class="text-muted-foreground">Sort by:</span>
			<Button
				variant={sortField === 'date_updated' ? 'secondary' : 'ghost'}
				size="sm"
				onclick={() => {
					if (sortField === 'date_updated') {
						sortAsc = !sortAsc;
					} else {
						sortField = 'date_updated';
						sortAsc = false;
					}
				}}
			>
				Date
				{#if sortField === 'date_updated'}
					{#if sortAsc}<ChevronUp class="ml-1 h-3 w-3" />{:else}<ChevronDown
							class="ml-1 h-3 w-3"
						/>{/if}
				{/if}
			</Button>
			<Button
				variant={sortField === 'title' ? 'secondary' : 'ghost'}
				size="sm"
				onclick={() => {
					if (sortField === 'title') {
						sortAsc = !sortAsc;
					} else {
						sortField = 'title';
						sortAsc = true;
					}
				}}
			>
				Name
				{#if sortField === 'title'}
					{#if sortAsc}<ChevronUp class="ml-1 h-3 w-3" />{:else}<ChevronDown
							class="ml-1 h-3 w-3"
						/>{/if}
				{/if}
			</Button>
		</div>
	</div>

	<!-- Dataset list -->
	<ScrollArea class="min-h-0 flex-1">
		<div class="space-y-1 p-2">
			{#if filteredDatasets.length === 0}
				<p class="px-4 py-8 text-center text-sm text-muted-foreground">No datasets found.</p>
			{:else}
				{#each filteredDatasets as dataset}
					<!-- The whole row selects; the selected dataset's metadata is in
					     the centre panel. -->
					<button
						type="button"
						class="block w-full cursor-pointer rounded-md px-3 py-2.5 text-left transition-colors
							{selectedDataset?.name === dataset.name
							? 'bg-primary/10 text-primary'
							: 'hover:bg-muted'}"
						aria-pressed={selectedDataset?.name === dataset.name}
						onclick={() => onSelect(dataset)}
					>
						<p class="flex items-start gap-2 text-sm font-bold leading-snug">
							<span class="min-w-0 flex-1">{dataset.title ?? dataset.name}</span>
							{#if unsavedNames.has(dataset.name)}
								<CircleAlert
									class="mt-0.5 size-4 shrink-0 text-warning-text"
									aria-hidden="true"
								/>
								<span class="sr-only">(filters not added to your request yet)</span>
							{/if}
						</p>
						<div class="mt-0.5 flex items-center gap-1.5">
							<p class="text-xs text-muted-foreground">
								{dataset.processing_class === 'filter_and_agg' ? 'Feature' : 'Raster'}
							</p>
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
					</button>
				{/each}
			{/if}
		</div>
	</ScrollArea>

	<!-- Count -->
	<div class="border-t px-4 py-2 text-xs text-muted-foreground">
		{filteredDatasets.length} of {datasets.length} datasets
	</div>
</div>
