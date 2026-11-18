<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import ClearSearchButton from '#lib/components/ClearSearchButton.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';
	import { ChevronRight, Search } from '@lucide/svelte';
	import type { Snippet } from 'svelte';
	import { searchBoundaries, type BoundaryPreset, type BoundaryResult } from '#lib/api.js';
	import { colorForIndex, lineWidthForLevel } from '#lib/utils/boundaryStyle.js';
	import SelectionLegend, { type LegendItem } from './SelectionLegend.svelte';

	interface Props {
		featuredBoundaries?: BoundaryResult[];
		proceedLabel?: string;
		proceedTooltip?: string;
		proceedDisabled?: boolean;
		selectedBoundaries?: BoundaryResult[]; // External selection state (optional)
		onSelect?: (boundaries: BoundaryResult[]) => void;
		onProceed?: (boundaries: BoundaryResult[]) => void;
		/** Clears the whole selection; shown at the left of the proceed row. */
		onClear?: () => void;
		/** Rendered directly under the search box, e.g. a note about the selection. */
		belowSearch?: Snippet;
		/** Rendered directly under the selection list, above the proceed button, e.g. coverage status. */
		belowSelection?: Snippet;
		/** At the right of the "What boundaries are available?" row, e.g. Custom upload */
		linkRowEnd?: Snippet;
		/** About the selection, behind an info button beside the selection count */
		selectionInfo?: Snippet;
		/** Show the selection list as its header only; its header calls onSelectionExpand */
		selectionCollapsed?: boolean;
		onSelectionExpand?: () => void;
		/** The search box text; bindable so the page's Restart can clear it. */
		searchText?: string;
		/** Presets offered in the search results, each with the boundary sets it adds */
		presets?: { preset: BoundaryPreset; members: BoundaryResult[] }[];
		/** How each selected set is drawn on the map, in selection order; derived from the selection when absent. */
		legendItems?: LegendItem[];
		/** Zoom the map to a selected set (a click on its row). */
		onZoom?: (id: number) => void;
		/** Highlight a selected set on the map, or clear it with null. */
		onHighlight?: (id: number | null) => void;
	}

	let {
		featuredBoundaries = [],
		proceedLabel = 'Find Data',
		proceedTooltip,
		proceedDisabled = false,
		selectedBoundaries: externalSelection = undefined,
		onSelect,
		onProceed,
		onClear,
		belowSearch,
		belowSelection,
		selectionInfo,
		linkRowEnd,
		selectionCollapsed = false,
		onSelectionExpand,
		searchText = $bindable(''),
		presets = [],
		legendItems,
		onZoom,
		onHighlight
	}: Props = $props();

	// Presets whose name, description or an alias matches the search, with members to add
	const presetMatches = $derived.by(() => {
		const q = searchText.trim().toLowerCase();
		if (!q) return [];
		return presets.filter(
			({ preset, members }) =>
				members.length > 0 &&
				[preset.name, preset.description ?? '', ...(preset.aliases ?? [])].some((text) =>
					text.toLowerCase().includes(q)
				)
		);
	});

	/** Add every boundary set of a preset not already selected, each as its own row. */
	function addPreset(members: BoundaryResult[]) {
		const have = new Set(selectedBoundaries.map((b) => b.id));
		const newSelection = [...selectedBoundaries, ...members.filter((b) => !have.has(b.id))];
		if (externalSelection === undefined) internalSelection = newSelection;
		onSelect?.(newSelection);
		searchText = '';
		autocompleteResults = [];
		inputEl?.focus();
	}

	let internalSelection = $state<BoundaryResult[]>([]);
	let searchFocused = $state(false);

	// Use external selection if provided, otherwise use internal
	let selectedBoundaries = $derived(externalSelection ?? internalSelection);

	let inputEl = $state<HTMLInputElement | null>(null);

	let legend = $derived<LegendItem[]>(
		legendItems ??
			selectedBoundaries.map((b, idx) => ({
				id: b.id,
				title: b.title || b.name,
				color: colorForIndex(idx),
				lineWidth: lineWidthForLevel(b.group_level),
				level: b.group_level,
				source: b.source_name,
				group: b.group_title
			}))
	);

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

	function proceed() {
		if (selectedBoundaries.length > 0 && !proceedDisabled) {
			onProceed?.(selectedBoundaries);
		}
	}
</script>

<!-- No box of its own: its parts are items of the panel's column (RequestPanel
     fill), so the selection list can shrink and scroll while the rest stays put -->
<div class="contents">
	<!-- Above the input and always shown, so typing doesn't move the search box -->
	<div class="flex items-center justify-between gap-2">
		<p class="text-sm">
			<a
				href="https://docs.geoquery.org/data_documentation/boundaries/"
				target="_blank"
				rel="noopener noreferrer"
				class="inline-block min-h-6 py-0.5 text-link hover:text-link-hover hover:underline">What boundaries are available?</a
			>
		</p>
		{@render linkRowEnd?.()}
	</div>

	<!-- Search Input -->
	<div class="relative">
		<Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
		<Input
			type="text"
			bind:ref={inputEl}
			bind:value={searchText}
			placeholder="Search boundaries..."
			aria-label="Search boundaries"
			class="pl-10 pr-8"
			onfocus={() => (searchFocused = true)}
			onblur={() => (searchFocused = false)}
		/>
		<ClearSearchButton
			value={searchText}
			onClear={() => {
				searchText = '';
				inputEl?.focus();
			}}
		/>

		<!-- Autocomplete dropdown -->
		{#if searchText.trim() && (autocompleteResults.length > 0 || presetMatches.length > 0)}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div
				class="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-md border bg-popover text-popover-foreground shadow-card"
				onmousedown={(e) => e.preventDefault()}
			>
				<!-- Presets first: one click adds each of their boundary sets -->
				{#each presetMatches as { preset, members } (preset.name)}
					{@const allIn = members.every((m) => selectedBoundaries.some((b) => b.id === m.id))}
					<button
						class="flex w-full items-baseline justify-between gap-2 border-b px-4 py-2 text-left text-sm hover:bg-accent disabled:opacity-50"
						disabled={allIn}
						onclick={() => addPreset(members)}
					>
						<span class="font-bold">{preset.name}</span>
						<span class="shrink-0 text-xs text-muted-foreground">Group · {members.length} boundary set{members.length === 1 ? '' : 's'}</span>
					</button>
				{/each}
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

		{#if searchText.trim() && autocompleteResults.length === 0 && presetMatches.length === 0 && !isLoading}
			<div class="absolute z-10 mt-1 w-full rounded-md border bg-popover p-4 text-sm text-muted-foreground shadow-card">
				No boundaries matching "{searchText}" were found.
			</div>
		{/if}
	</div>

	{@render belowSearch?.()}

	<!-- Featured boundaries: a way to start, so only until something is selected -->
	{#if !searchText.trim() && featuredBoundaries.length > 0 && selectedBoundaries.length === 0}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div onmousedown={(e) => e.preventDefault()}>
			<p class="text-sm text-muted-foreground">
				<strong>Featured Boundaries: </strong>
				{#each featuredBoundaries as boundary, i}
					<button
						class="inline-block min-h-6 py-0.5 text-left text-link hover:text-link-hover hover:underline disabled:opacity-50"
						disabled={selectedBoundaries.some((b) => b.id === boundary.id)}
						onclick={() => addBoundary(boundary)}
					>
						{boundary.title || boundary.name}{i < featuredBoundaries.length - 1 ? ', ' : ''}
					</button>
				{/each}
			</p>
		</div>
	{/if}

	<!-- The selection as a key to the map, then whatever the page shows about it -->
	{#if selectedBoundaries.length > 0}
		<SelectionLegend
			items={legend}
			onZoom={onZoom}
			onRemove={removeBoundary}
			onHighlight={onHighlight}
			info={selectionInfo}
			collapsed={selectionCollapsed}
			onExpand={onSelectionExpand}
		/>
		{@render belowSelection?.()}
	{/if}

	<!-- Action buttons: the proceed button always, disabled until something is
	     selected; Clear All once there's something to clear -->
	{#snippet proceedButton()}
		<Button size="sm" disabled={proceedDisabled || selectedBoundaries.length === 0} onclick={proceed}>
			{proceedLabel}
			<ChevronRight />
		</Button>
	{/snippet}
	<div class="flex items-center justify-between gap-2 pt-2">
		{#if onClear && selectedBoundaries.length > 0}
				<Button
					size="sm"
					variant="outline"
					onclick={onClear}
					class="text-muted-foreground hover:text-destructive"
				>
					Clear All
				</Button>
			{:else}
				<span></span>
			{/if}
		{#if proceedTooltip}
			<Tooltip.Root>
				<Tooltip.Trigger>{@render proceedButton()}</Tooltip.Trigger>
				<Tooltip.Content>{proceedTooltip}</Tooltip.Content>
			</Tooltip.Root>
		{:else}
			{@render proceedButton()}
		{/if}
	</div>
</div>