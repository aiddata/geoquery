<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Separator } from '$lib/components/ui/separator';
	import { ChevronLeft, ChevronRight, Search } from '@lucide/svelte';

	interface Boundary {
		id: string;
		name: string;
		title: string;
	}

	interface Props {
		boundaries?: Boundary[];
		featuredBoundaries?: Boundary[];
		onSelect?: (boundary: Boundary, subboundary?: string) => void;
	}

	let { boundaries = [], featuredBoundaries = [], onSelect }: Props = $props();

	let searchText = $state('');
	let selectedBoundary = $state<Boundary | null>(null);
	let subboundaries = $state<Boundary[]>([]);
	let selectedSubboundary = $state<string | null>(null);

	const filteredBoundaries = $derived(
		boundaries.filter(
			(b) =>
				b.name.toLowerCase().includes(searchText.toLowerCase()) ||
				b.title.toLowerCase().includes(searchText.toLowerCase())
		)
	);

	function selectBoundary(boundary: Boundary) {
		selectedBoundary = boundary;
		searchText = boundary.title || boundary.name;
		// TODO: Load subboundaries from API
		subboundaries = [];
	}

	function goBack() {
		selectedBoundary = null;
		selectedSubboundary = null;
		searchText = '';
	}

	function proceed() {
		if (selectedBoundary && onSelect) {
			onSelect(selectedBoundary, selectedSubboundary ?? undefined);
		}
	}
</script>

<div class="rounded-lg border bg-card p-6 shadow-lg">
	<h2 class="mb-4 text-xl font-semibold text-primary">
		Select a Boundary to Begin Data Extraction
	</h2>

	<!-- Search Input -->
	<div class="relative">
		<Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
		<input
			type="text"
			bind:value={searchText}
			placeholder="Search boundaries..."
			class="w-full rounded-md border bg-background py-2 pl-10 pr-4 text-sm outline-none focus:ring-2 focus:ring-ring"
		/>

		<!-- Autocomplete dropdown -->
		{#if searchText && !selectedBoundary && filteredBoundaries.length > 0}
			<div
				class="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-md border bg-popover shadow-lg"
			>
				{#each filteredBoundaries.slice(0, 10) as boundary}
					<button
						class="w-full px-4 py-2 text-left text-sm hover:bg-accent"
						onclick={() => selectBoundary(boundary)}
					>
						{boundary.title || boundary.name}
					</button>
				{/each}
			</div>
		{/if}

		{#if searchText && !selectedBoundary && filteredBoundaries.length === 0}
			<div class="absolute z-10 mt-1 w-full rounded-md border bg-popover p-4 text-sm shadow-lg">
				No boundaries matching "{searchText}" were found.
			</div>
		{/if}
	</div>

	<!-- Featured boundaries (shown when no selection) -->
	{#if !selectedBoundary && featuredBoundaries.length > 0}
		<div class="mt-4">
			<p class="text-sm text-muted-foreground">
				<strong>Featured Boundaries: </strong>
				{#each featuredBoundaries.slice(0, 5) as boundary, i}
					<button class="text-primary hover:underline" onclick={() => selectBoundary(boundary)}>
						{boundary.name}{i < Math.min(featuredBoundaries.length, 5) - 1 ? ', ' : ''}
					</button>
				{/each}
			</p>
		</div>
	{/if}

	<!-- Subboundary selection (shown after boundary selected) -->
	{#if selectedBoundary && subboundaries.length > 0}
		<Separator class="my-4" />

		<fieldset class="space-y-2">
			<legend class="text-sm font-medium">Select a Subboundary</legend>
			{#each subboundaries as sub}
				<label class="flex items-center gap-2">
					<input
						type="radio"
						name="subboundary"
						value={sub.name}
						bind:group={selectedSubboundary}
						class="h-4 w-4"
					/>
					<span class="text-sm">{sub.title}</span>
				</label>
			{/each}
		</fieldset>

		<Separator class="my-4" />

		<div class="flex justify-between">
			<Button variant="ghost" onclick={goBack}>
				<ChevronLeft class="mr-2 h-4 w-4" />
				Back
			</Button>
			<Button onclick={proceed}>
				Search Datasets
				<ChevronRight class="ml-2 h-4 w-4" />
			</Button>
		</div>
	{/if}

	<!-- Proceed button (when boundary selected but no subboundaries) -->
	{#if selectedBoundary && subboundaries.length === 0}
		<div class="mt-4 flex justify-between">
			<Button variant="ghost" onclick={goBack}>
				<ChevronLeft class="mr-2 h-4 w-4" />
				Back
			</Button>
			<Button onclick={proceed}>
				Search Datasets
				<ChevronRight class="ml-2 h-4 w-4" />
			</Button>
		</div>
	{/if}
</div>
