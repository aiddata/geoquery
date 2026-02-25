<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { ChevronLeft, ChevronRight, Search } from '@lucide/svelte';
	import { searchBoundaries, type BoundaryResult } from '$lib/api';

	interface Props {
		featuredBoundaries?: BoundaryResult[];
		onSelect?: (boundary: BoundaryResult | null) => void;
		onProceed?: (boundary: BoundaryResult) => void;
	}

	let { featuredBoundaries = [], onSelect, onProceed }: Props = $props();

	let searchText = $state('');
	let selectedBoundary = $state<BoundaryResult | null>(null);

	let autocompleteResults = $state<BoundaryResult[]>([]);
	let isLoading = $state(false);

	// Debounced autocomplete from API
	$effect(() => {
		const query = searchText;

		if (selectedBoundary || !query.trim()) {
			autocompleteResults = [];
			return;
		}

		isLoading = true;
		const timeout = setTimeout(async () => {
			try {
				autocompleteResults = await searchBoundaries(query, 10);
			} catch (e) {
				console.error('Autocomplete fetch failed:', e);
				autocompleteResults = [];
			} finally {
				isLoading = false;
			}
		}, 300);

		return () => {
			clearTimeout(timeout);
			isLoading = false;
		};
	});

	function selectBoundary(boundary: BoundaryResult) {
		selectedBoundary = boundary;
		searchText = boundary.title || boundary.name;
		autocompleteResults = [];
		onSelect?.(boundary);
	}

	function goBack() {
		selectedBoundary = null;
		searchText = '';
		autocompleteResults = [];
		onSelect?.(null);
	}

	function proceed() {
		if (selectedBoundary) {
			onProceed?.(selectedBoundary);
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
		{#if searchText && !selectedBoundary}
			<div
				class="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-md border bg-popover shadow-lg"
			>
				{#if isLoading}
					<div class="px-4 py-2 text-sm text-muted-foreground">Searching...</div>
				{:else if autocompleteResults.length > 0}
					{#each autocompleteResults as boundary}
						<button
							class="w-full px-4 py-2 text-left text-sm hover:bg-accent"
							onclick={() => selectBoundary(boundary)}
						>
							{boundary.title || boundary.name}
						</button>
					{/each}
				{:else if searchText.trim().length > 0}
					<div class="px-4 py-2 text-sm text-muted-foreground">
						No boundaries matching "{searchText}" were found.
					</div>
				{/if}
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
						{boundary.title || boundary.name}{i < Math.min(featuredBoundaries.length, 5) - 1
							? ', '
							: ''}
					</button>
				{/each}
			</p>
		</div>
	{/if}

	<!-- Proceed / Back buttons (when boundary selected) -->
	{#if selectedBoundary}
		<div class="mt-4 flex justify-between">
			<Button variant="ghost" onclick={goBack}>
				<ChevronLeft class="mr-2 h-4 w-4" />
				Back
			</Button>
			<Button onclick={proceed}>
				Find Data
				<ChevronRight class="ml-2 h-4 w-4" />
			</Button>
		</div>
	{/if}
</div>
