<script lang="ts">
	import { Input } from '$lib/components/ui/input';
	import * as Select from '$lib/components/ui/select';
	import * as Card from '$lib/components/ui/card';
	import { ScrollArea } from '$lib/components/ui/scroll-area';
	import { Button } from '$lib/components/ui/button';
	import { Search, ArrowUpDown, ChevronDown, ChevronUp, ExternalLink } from '@lucide/svelte';
	import type { DatasetSummary, DatasetCategory } from '$lib/api';

	interface Props {
		datasets: DatasetSummary[];
		categories: DatasetCategory[];
		selectedDataset: DatasetSummary | null;
		onSelect: (dataset: DatasetSummary) => void;
	}

	let { datasets, categories, selectedDataset, onSelect }: Props = $props();

	let searchText = $state('');
	let searchFocused = $state(false);
	let selectedCategory = $state('all');
	let sortField = $state<'date_updated' | 'title'>('date_updated');
	let sortAsc = $state(false);
	let expandedDataset = $state<string | null>(null);

	let filteredDatasets = $derived.by(() => {
		let result = datasets;

		// Filter by category tag
		if (selectedCategory !== 'all') {
			result = result.filter((d) => d.tags?.includes(selectedCategory));
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

	function toggleExpand(name: string) {
		expandedDataset = expandedDataset === name ? null : name;
	}
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
				placeholder={selectedDataset ? (selectedDataset.title ?? selectedDataset.name) : 'Search datasets...'}
				class="pl-10 {!searchFocused && selectedDataset && !searchText ? 'placeholder:text-foreground' : ''}"
				onfocus={() => (searchFocused = true)}
				onblur={() => (searchFocused = false)}
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
	<ScrollArea class="flex-1">
		<div class="space-y-1 p-2">
			{#if filteredDatasets.length === 0}
				<p class="px-4 py-8 text-center text-sm text-muted-foreground">No datasets found.</p>
			{:else}
				{#each filteredDatasets as dataset}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div
						class="cursor-pointer rounded-md px-3 py-2.5 text-left transition-colors
							{selectedDataset?.name === dataset.name
							? 'bg-primary/10 text-primary'
							: 'hover:bg-muted'}"
						onclick={() => onSelect(dataset)}
					>
						<div class="flex items-start justify-between gap-2">
							<div class="flex-1">
								<p class="text-sm font-medium leading-snug">
									{dataset.title ?? dataset.name}
								</p>
								<p class="mt-0.5 text-xs text-muted-foreground">
									{dataset.type === 'release' ? 'AidData' : 'Raster'}
								</p>
							</div>
							<button
								class="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground"
								onclick={(e: MouseEvent) => { e.stopPropagation(); toggleExpand(dataset.name); }}
								aria-label="Toggle details"
							>
								{#if expandedDataset === dataset.name}
									<ChevronUp class="h-4 w-4" />
								{:else}
									<ChevronDown class="h-4 w-4" />
								{/if}
							</button>
						</div>

						{#if expandedDataset === dataset.name}
							<div class="mt-2 space-y-1.5 text-xs text-muted-foreground">
								{#if dataset.description}
									<p>{dataset.description}</p>
								{/if}
								{#if dataset.source_name}
									<p>
										Source: {dataset.source_name}
										{#if dataset.source_url}
											<a
												href={dataset.source_url}
												target="_blank"
												rel="noopener noreferrer"
												class="inline-flex items-center gap-1 text-primary hover:underline"
												onclick={(e: MouseEvent) => e.stopPropagation()}
											>
												<ExternalLink class="h-3 w-3" />
											</a>
										{/if}
									</p>
								{/if}
							</div>
						{/if}
					</div>
				{/each}
			{/if}
		</div>
	</ScrollArea>

	<!-- Count -->
	<div class="border-t px-4 py-2 text-xs text-muted-foreground">
		{filteredDatasets.length} of {datasets.length} datasets
	</div>
</div>
