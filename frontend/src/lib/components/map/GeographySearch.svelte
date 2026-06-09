<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import * as Tooltip from '$lib/components/ui/tooltip';
	import { ChevronLeft, ChevronRight, Search, X } from '@lucide/svelte';
	import { searchBoundaries, type BoundaryResult } from '$lib/api';
	import { colorForIndex } from '$lib/utils/boundaryStyle';

	interface Props {
		featuredBoundaries?: BoundaryResult[];
		proceedLabel?: string;
		proceedTooltip?: string;
		selectedBoundaries?: BoundaryResult[]; // External selection state (optional)
		onSelect?: (boundaries: BoundaryResult[]) => void;
		onProceed?: (boundaries: BoundaryResult[]) => void;
	}

	let {
		featuredBoundaries = [],
		proceedLabel = 'Find Data',
		proceedTooltip,
		selectedBoundaries: externalSelection = undefined,
		onSelect,
		onProceed
	}: Props = $props();

	let internalSelection = $state<BoundaryResult[]>([]);
	let searchText = $state('');
	let searchFocused = $state(false);

	// Use external selection if provided, otherwise use internal
	let selectedBoundaries = $derived(externalSelection ?? internalSelection);

	let inputEl: HTMLInputElement | undefined;

	let autocompleteResults = $state<BoundaryResult[]>([]);
	let isLoading = $state(false);

	// Debounced autocomplete from API
	$effect(() => {
		const query = searchText.trim();

		if (!query) {
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

	function addBoundary(boundary: BoundaryResult) {
		// Avoid duplicates
		if (!selectedBoundaries.some((b) => b.id === boundary.id)) {
			const newSelection = [...selectedBoundaries, boundary];
			if (externalSelection === undefined) {
				internalSelection = newSelection;
			}
			onSelect?.(newSelection);
		}
		searchText = '';
		autocompleteResults = [];
		inputEl?.focus();
	}

	function removeBoundary(id: number) {
		const newSelection = selectedBoundaries.filter((b) => b.id !== id);
		if (externalSelection === undefined) {
			internalSelection = newSelection;
		}
		onSelect?.(newSelection);
	}

	function goBack() {
		const newSelection: BoundaryResult[] = [];
		if (externalSelection === undefined) {
			internalSelection = newSelection;
		}
		searchText = '';
		autocompleteResults = [];
		onSelect?.(newSelection);
	}

	function proceed() {
		if (selectedBoundaries.length > 0) {
			onProceed?.(selectedBoundaries);
		}
	}
</script>

<div class="space-y-3">
	<!-- Selected chips -->
	{#if selectedBoundaries.length > 0}
		<div class="max-h-20 overflow-y-auto flex flex-wrap gap-1">
			{#each selectedBoundaries as boundary, idx (boundary.id)}
				<div class="inline-flex items-center gap-1 rounded-md bg-primary/15 px-2 py-0.5 text-xs font-medium">
					<span
						class="inline-block h-2.5 w-2.5 rounded-sm shrink-0"
						style="background-color: {colorForIndex(idx)}"
						aria-hidden="true"
					></span>
					<span class="truncate max-w-xs">{boundary.title || boundary.name}</span>
					<button
						class="inline-flex rounded p-0.5 hover:bg-primary/30 transition-colors"
						onclick={() => removeBoundary(boundary.id)}
						aria-label="Remove boundary"
					>
						<X class="h-3 w-3" />
					</button>
				</div>
			{/each}
		</div>
	{/if}

	<!-- Search Input -->
	<div class="relative">
		<Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
		<input
			type="text"
			bind:this={inputEl}
			bind:value={searchText}
			placeholder="Search boundaries..."
			class="w-full rounded-md border bg-background py-2 pl-10 pr-4 text-sm outline-none focus:ring-2 focus:ring-ring"
			onfocus={() => (searchFocused = true)}
			onblur={() => (searchFocused = false)}
		/>

		<!-- Autocomplete dropdown -->
		{#if searchText.trim() && autocompleteResults.length > 0}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div
				class="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-md border bg-popover shadow-lg"
				onmousedown={(e) => e.preventDefault()}
			>
				{#if isLoading}
					<div class="px-4 py-2 text-sm text-muted-foreground">Searching...</div>
				{:else}
					{#each autocompleteResults as boundary}
						<button
							class="w-full px-4 py-2 text-left text-sm hover:bg-accent disabled:opacity-50"
							disabled={selectedBoundaries.some((b) => b.id === boundary.id)}
							onclick={() => addBoundary(boundary)}
						>
							{boundary.title || boundary.name}
						</button>
					{/each}
				{/if}
			</div>
		{/if}

		{#if searchText.trim() && autocompleteResults.length === 0 && !isLoading}
			<div class="absolute z-10 mt-1 w-full rounded-md border bg-popover p-4 text-sm text-muted-foreground shadow-lg">
				No boundaries matching "{searchText}" were found.
			</div>
		{/if}
	</div>

	<!-- Featured boundaries (shown when no text in search) -->
	{#if !searchText.trim() && featuredBoundaries.length > 0}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div onmousedown={(e) => e.preventDefault()}>
			<p class="text-sm text-muted-foreground">
				<strong>Featured Boundaries: </strong>
				{#each featuredBoundaries as boundary, i}
					<button
						class="text-primary hover:underline disabled:opacity-50"
						disabled={selectedBoundaries.some((b) => b.id === boundary.id)}
						onclick={() => addBoundary(boundary)}
					>
						{boundary.title || boundary.name}{i < featuredBoundaries.length - 1 ? ', ' : ''}
					</button>
				{/each}
			</p>
		</div>
	{/if}

	<!-- Action buttons -->
	{#if selectedBoundaries.length > 0}
		<div class="flex justify-between pt-2">
			<Button variant="ghost" size="sm" onclick={goBack}>
				<ChevronLeft class="mr-1 h-4 w-4" />
				Clear
			</Button>
			{#if proceedTooltip}
				<Tooltip.Root>
					<Tooltip.Trigger>
						<Button size="sm" onclick={proceed}>
							{proceedLabel}
							<ChevronRight class="ml-1 h-4 w-4" />
						</Button>
					</Tooltip.Trigger>
					<Tooltip.Content>{proceedTooltip}</Tooltip.Content>
				</Tooltip.Root>
			{:else}
				<Button size="sm" onclick={proceed}>
					{proceedLabel}
					<ChevronRight class="ml-1 h-4 w-4" />
				</Button>
			{/if}
		</div>
	{/if}
</div>