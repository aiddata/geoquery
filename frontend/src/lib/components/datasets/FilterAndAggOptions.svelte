<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { ScrollArea } from '$lib/components/ui/scroll-area';
	import type { DatasetFilter } from '$lib/api';
	import type { FilterSelection, RangeSelection, CategoricalSelection } from '$lib/stores/cart';

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
</script>

<div class="flex flex-wrap gap-4 p-4">
	{#each Object.entries(filters) as [key, filter]}
		{#if filter.type === 'range'}
			{@const sel = getRangeSelection(key, filter)}
			<Card.Root class="w-56 shrink-0">
				<Card.Header class="pb-2">
					<Card.Title class="text-sm">{key}</Card.Title>
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
						{key}
						<span class="ml-1 text-xs font-normal text-muted-foreground">
							({sel.selected.length}/{filter.categories.length})
						</span>
					</Card.Title>
				</Card.Header>
				<Card.Content class="pt-0">
					<ScrollArea class="h-52">
						<div class="space-y-2 pr-3">
							<!-- Select All -->
							<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
							<div
								class="flex cursor-pointer items-center gap-2 border-b pb-2"
								onclick={() => setSelection(key, { type: 'categorical', selected: allSelected ? [] : [...filter.categories] })}
							>
								<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
								<span onclick={(e) => e.stopPropagation()}>
									<Checkbox
										checked={allSelected}
										onCheckedChange={() => setSelection(key, { type: 'categorical', selected: allSelected ? [] : [...filter.categories] })}
									/>
								</span>
								<Label class="cursor-pointer text-xs font-medium">All</Label>
							</div>

							{#each filter.categories as category}
								{@const checked = sel.selected.includes(category)}
								<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
								<div
									class="flex cursor-pointer items-center gap-2"
									onclick={() => {
										const next = checked
											? sel.selected.filter((c) => c !== category)
											: [...sel.selected, category];
										setSelection(key, { type: 'categorical', selected: next });
									}}
								>
									<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
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
	{/each}
</div>
