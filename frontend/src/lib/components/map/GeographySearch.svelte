<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
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

	let inputEl = $state<HTMLInputElement | null>(null);

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
				autocompleteResults = await searchBoundaries(query, 50);
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
				<div class="inline-flex items-center gap-1 rounded-md bg-primary/15 py-0.5 pr-0.5 pl-2 text-sm font-bold">
					<span
						class="inline-block size-3 shrink-0 rounded-sm border border-chart-edge"
						style="background-color: {colorForIndex(idx)}"
						data-swatch
						aria-hidden="true"
					></span>
					<span class="truncate max-w-xs">{boundary.title || boundary.name}</span>
					<Button
						variant="ghost"
						size="icon-sm"
						class="size-6 hover:bg-primary/30"
						onclick={() => removeBoundary(boundary.id)}
						aria-label="Remove {boundary.title || boundary.name}"
					>
						<X class="size-3.5" />
					</Button>
				</div>
			{/each}
		</div>
	{/if}

	<!-- Search Input -->
	<div class="relative">
		<Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
		<Input
			type="text"
			bind:ref={inputEl}
			bind:value={searchText}
			placeholder="Search boundaries..."
			aria-label="Search boundaries"
			class="pl-10"
			onfocus={() => (searchFocused = true)}
			onblur={() => (searchFocused = false)}
		/>

		<!-- Autocomplete dropdown -->
		{#if searchText.trim() && autocompleteResults.length > 0}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div
				class="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-md border bg-popover text-popover-foreground shadow-card"
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
			<div class="absolute z-10 mt-1 w-full rounded-md border bg-popover p-4 text-sm text-muted-foreground shadow-card">
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
						class="text-link hover:text-link-hover hover:underline disabled:opacity-50"
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
				<ChevronLeft />
				Clear
			</Button>
			{#if proceedTooltip}
				<Tooltip.Root>
					<Tooltip.Trigger>
						<Button size="sm" onclick={proceed}>
							{proceedLabel}
							<ChevronRight />
						</Button>
					</Tooltip.Trigger>
					<Tooltip.Content>{proceedTooltip}</Tooltip.Content>
				</Tooltip.Root>
			{:else}
				<Button size="sm" onclick={proceed}>
					{proceedLabel}
					<ChevronRight />
				</Button>
			{/if}
		</div>
	{/if}
</div>