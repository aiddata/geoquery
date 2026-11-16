<script lang="ts">
	import * as Card from '#lib/components/ui/card/index.js';
	import { Checkbox } from '#lib/components/ui/checkbox/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { ScrollArea } from '#lib/components/ui/scroll-area/index.js';
	import OptionsSection from './OptionsSection.svelte';
	import type { DatasetFilter } from '#lib/api.js';
	import type { FilterSelection, RangeSelection, CategoricalSelection } from '#lib/stores/cart.js';

	interface Props {
		filters: Record<string, DatasetFilter>;
		selections: Record<string, FilterSelection>;
		onSelectionsChange: (s: Record<string, FilterSelection>) => void;
	}

	let { filters, selections, onSelectionsChange }: Props = $props();

	function setSelection(key: string, val: FilterSelection) {
		onSelectionsChange({ ...selections, [key]: val });
	}

	function getRangeSelection(key: string, filter: Extract<DatasetFilter, { type: 'range' }>): RangeSelection {
		const s = selections[key];
		if (s?.type === 'range') return s;
		return { type: 'range', start: filter.min, end: filter.max };
	}

	function getCategoricalSelection(key: string, filter: Extract<DatasetFilter, { type: 'categorical' }>): CategoricalSelection {
		const s = selections[key];
		if (s?.type === 'categorical') return s;
		return { type: 'categorical', selected: [...filter.categories] };
	}

	function clamp(val: number, min: number, max: number) {
		return Math.max(min, Math.min(max, val));
	}

	// Filters marked aggregate: false split the results into a column per
	// selected value (one per combination when there are several); the rest
	// (aggregate defaults to true) only narrow which records are added up.
	const entries = $derived(Object.entries(filters));
	const splitFields = $derived(entries.filter(([, f]) => f.aggregate === false));
	const filterFields = $derived(entries.filter(([, f]) => f.aggregate !== false));

	// Columns the current split choices produce for each area.
	const splitColumns = $derived(
		splitFields.reduce(
			(n, [key, f]) => n * (f.type === 'categorical' ? getCategoricalSelection(key, f).selected.length : 1),
			1
		)
	);
</script>

{#snippet filterCard(key: string, filter: DatasetFilter)}
		{#if filter.type === 'range'}
			{@const sel = getRangeSelection(key, filter)}
			<Card.Root class="w-56 shrink-0">
				<Card.Header class="pb-2">
					<Card.Title class="text-sm">{filter.display ?? key}</Card.Title>
					<p class="text-xs text-muted-foreground">Range: {filter.min}–{filter.max}</p>
				</Card.Header>
				<Card.Content class="pt-0">
					<div class="flex items-center gap-2">
						<div class="flex-1 space-y-1">
							<Label class="text-xs text-muted-foreground">From</Label>
							<Input
								type="number"
								min={filter.min}
								max={sel.end}
								value={sel.start}
								class="h-8 text-xs"
								oninput={(e) => {
									const v = clamp(parseInt((e.target as HTMLInputElement).value) || filter.min, filter.min, sel.end);
									setSelection(key, { ...sel, start: v });
								}}
							/>
						</div>
						<span class="mt-5 text-xs text-muted-foreground">–</span>
						<div class="flex-1 space-y-1">
							<Label class="text-xs text-muted-foreground">To</Label>
							<Input
								type="number"
								min={sel.start}
								max={filter.max}
								value={sel.end}
								class="h-8 text-xs"
								oninput={(e) => {
									const v = clamp(parseInt((e.target as HTMLInputElement).value) || filter.max, sel.start, filter.max);
									setSelection(key, { ...sel, end: v });
								}}
							/>
						</div>
					</div>
				</Card.Content>
			</Card.Root>
		{:else if filter.type === 'categorical'}
			{@const sel = getCategoricalSelection(key, filter)}
			{@const allSelected = sel.selected.length === filter.categories.length}
			<Card.Root class="w-64 shrink-0">
				<Card.Header class="pb-2">
					<Card.Title class="text-sm">
						{filter.display ?? key}
						<span class="ml-1 text-xs font-normal text-muted-foreground">
							({sel.selected.length}/{filter.categories.length})
						</span>
					</Card.Title>
				</Card.Header>
				<Card.Content class="pt-0">
					<ScrollArea class="h-52">
						<div class="space-y-2 pr-3">
							<!-- Select All -->
							<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
							<div
								class="flex cursor-pointer items-center gap-2 border-b pb-2"
								onclick={() => setSelection(key, { type: 'categorical', selected: allSelected ? [] : [...filter.categories] })}
							>
								<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
								<span onclick={(e) => e.stopPropagation()}>
									<Checkbox
										checked={allSelected}
										onCheckedChange={() => setSelection(key, { type: 'categorical', selected: allSelected ? [] : [...filter.categories] })}
									/>
								</span>
								<Label class="cursor-pointer text-xs font-bold">All</Label>
							</div>

							{#each filter.categories as category}
								{@const checked = sel.selected.includes(category)}
								<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
								<div
									class="flex cursor-pointer items-center gap-2"
									onclick={() => {
										const next = checked
											? sel.selected.filter((c) => c !== category)
											: [...sel.selected, category];
										setSelection(key, { type: 'categorical', selected: next });
									}}
								>
									<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
									<span onclick={(e) => e.stopPropagation()}>
										<Checkbox
											{checked}
											onCheckedChange={() => {
												const next = checked
													? sel.selected.filter((c) => c !== category)
													: [...sel.selected, category];
												setSelection(key, { type: 'categorical', selected: next });
											}}
										/>
									</span>
									<Label class="cursor-pointer text-xs font-normal capitalize">{category}</Label>
								</div>
							{/each}
						</div>
					</ScrollArea>
				</Card.Content>
			</Card.Root>
		{/if}
{/snippet}

<!-- Rendered inside the Customize page's options column, after Measure. -->
{#if splitFields.length > 0}
	<OptionsSection
		id="split"
		title="Split results by"
		summary="Each value you select gets its own column in your results."
		help="Instead of a single total, each area gets a separate column for every selected value, for example one column per year. With more than one split field, there is a column for every combination. Unselected values are left out."
		note="{splitColumns} column{splitColumns === 1 ? '' : 's'} per area"
	>
		<div class="flex flex-wrap gap-4">
			{#each splitFields as [key, filter] (key)}
				{@render filterCard(key, filter)}
			{/each}
		</div>
	</OptionsSection>
{/if}

{#if filterFields.length > 0}
	<OptionsSection
		id="filter"
		title="Filter records"
		summary="Only matching records are counted, and they are added together into one value."
		help="These narrow which records are included. Records outside a range, or with a value you've unselected, are left out. Everything that matches is combined into one total per area (or per column, when results are split)."
	>
		<div class="flex flex-wrap gap-4">
			{#each filterFields as [key, filter] (key)}
				{@render filterCard(key, filter)}
			{/each}
		</div>
	</OptionsSection>
{/if}
