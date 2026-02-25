<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Button } from '$lib/components/ui/button';
	import { ScrollArea } from '$lib/components/ui/scroll-area';
	import { Search, X, RotateCcw, Plus } from '@lucide/svelte';
	import type { DatasetDetail, DatasetField } from '$lib/api';

	interface Props {
		dataset: DatasetDetail;
		filters: Record<string, string[]>;
		onFiltersChange: (filters: Record<string, string[]>) => void;
	}

	let { dataset, filters, onFiltersChange }: Props = $props();

	// Track which fields are actively shown as filter cards
	let activeFields = $state<string[]>([]);
	// Per-card search text
	let cardSearchText = $state<Record<string, string>>({});
	// Show "add filter" menu
	let showAddMenu = $state(false);

	// Initialize active fields from dataset defaults
	$effect(() => {
		if (dataset?.fields) {
			activeFields = Object.entries(dataset.fields)
				.filter(([_, f]) => f.is_default)
				.map(([key]) => key);

			// Initialize filters with "All" for each default field
			const initial: Record<string, string[]> = {};
			for (const key of activeFields) {
				initial[key] = ['All'];
			}
			onFiltersChange(initial);
		}
	});

	function toggleValue(fieldKey: string, value: string) {
		const current = filters[fieldKey] ?? ['All'];

		if (value === 'All') {
			onFiltersChange({ ...filters, [fieldKey]: ['All'] });
			return;
		}

		let next: string[];
		if (current.includes('All')) {
			// Switching from "All" to specific value
			next = [value];
		} else if (current.includes(value)) {
			next = current.filter((v) => v !== value);
			if (next.length === 0) next = ['All'];
		} else {
			next = [...current, value];
		}

		onFiltersChange({ ...filters, [fieldKey]: next });
	}

	function resetField(fieldKey: string) {
		onFiltersChange({ ...filters, [fieldKey]: ['All'] });
	}

	function removeField(fieldKey: string) {
		activeFields = activeFields.filter((k) => k !== fieldKey);
		const next = { ...filters };
		delete next[fieldKey];
		onFiltersChange(next);
	}

	function addField(fieldKey: string) {
		activeFields = [...activeFields, fieldKey];
		onFiltersChange({ ...filters, [fieldKey]: ['All'] });
		showAddMenu = false;
	}

	function isChecked(fieldKey: string, value: string): boolean {
		const current = filters[fieldKey] ?? ['All'];
		if (value === 'All') return current.includes('All');
		return !current.includes('All') && current.includes(value);
	}

	function selectedCount(fieldKey: string): number {
		const current = filters[fieldKey] ?? ['All'];
		if (current.includes('All')) return 0;
		return current.length;
	}

	let inactiveFields = $derived(
		Object.entries(dataset?.fields ?? {})
			.filter(([key]) => !activeFields.includes(key))
			.map(([key, field]) => ({ key, field }))
	);

	function getFilteredDistinct(fieldKey: string, field: DatasetField): string[] {
		if (field.type !== 'list' || !Array.isArray(field.distinct)) return [];
		const search = (cardSearchText[fieldKey] ?? '').toLowerCase();
		if (!search) return field.distinct as string[];
		return (field.distinct as string[]).filter((v) => v.toLowerCase().includes(search));
	}
</script>

<div class="flex gap-4 overflow-x-auto p-4">
	{#each activeFields as fieldKey}
		{@const field = dataset.fields[fieldKey]}
		{#if field}
			<Card.Root class="w-72 shrink-0">
				<Card.Header class="pb-2">
					<div class="flex items-center justify-between">
						<Card.Title class="text-sm">
							{field.display}
							{#if selectedCount(fieldKey) > 0}
								<span class="ml-1 text-xs text-muted-foreground">
									({selectedCount(fieldKey)})
								</span>
							{/if}
						</Card.Title>
						<div class="flex items-center gap-1">
							{#if !filters[fieldKey]?.includes('All')}
								<Button
									variant="ghost"
									size="sm"
									class="h-6 w-6 p-0"
									onclick={() => resetField(fieldKey)}
									aria-label="Reset filter"
								>
									<RotateCcw class="h-3 w-3" />
								</Button>
							{/if}
							<Button
								variant="ghost"
								size="sm"
								class="h-6 w-6 p-0"
								onclick={() => removeField(fieldKey)}
								aria-label="Remove filter"
							>
								<X class="h-3 w-3" />
							</Button>
						</div>
					</div>
				</Card.Header>
				<Card.Content class="pt-0">
					{#if field.type === 'list' && Array.isArray(field.distinct)}
						<!-- Search within this filter -->
						<div class="relative mb-2">
							<Search
								class="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground"
							/>
							<Input
								value={cardSearchText[fieldKey] ?? ''}
								oninput={(e) => {
									cardSearchText = {
										...cardSearchText,
										[fieldKey]: (e.target as HTMLInputElement).value
									};
								}}
								placeholder="Search..."
								class="h-7 pl-7 text-xs"
							/>
						</div>

						<ScrollArea class="h-48">
							<div class="space-y-1.5 pr-3">
								<!-- "All" option -->
								<div class="flex items-center gap-2">
									<Checkbox
										checked={isChecked(fieldKey, 'All')}
										onCheckedChange={() => toggleValue(fieldKey, 'All')}
									/>
									<Label class="text-xs font-normal">All</Label>
								</div>

								{#each getFilteredDistinct(fieldKey, field) as value}
									{#if value !== 'All'}
										<div class="flex items-center gap-2">
											<Checkbox
												checked={isChecked(fieldKey, value)}
												onCheckedChange={() => toggleValue(fieldKey, value)}
											/>
											<Label class="text-xs font-normal">{value}</Label>
										</div>
									{/if}
								{/each}
							</div>
						</ScrollArea>
					{:else if field.type === 'slider' && Array.isArray(field.distinct)}
						<!-- Range inputs for numeric fields -->
						<div class="space-y-3 py-2">
							<div class="flex items-center gap-2">
								<div class="flex-1">
									<Label class="text-xs text-muted-foreground">Min</Label>
									<Input type="number" value={String(field.distinct[0])} class="h-8 text-xs" />
								</div>
								<span class="mt-5 text-muted-foreground">-</span>
								<div class="flex-1">
									<Label class="text-xs text-muted-foreground">Max</Label>
									<Input type="number" value={String(field.distinct[1])} class="h-8 text-xs" />
								</div>
							</div>
							<!-- Placeholder for range slider -->
							<div class="h-2 rounded-full bg-muted">
								<div class="h-2 w-full rounded-full bg-primary/30"></div>
							</div>
						</div>
					{/if}
				</Card.Content>
			</Card.Root>
		{/if}
	{/each}

	<!-- Add Filter button -->
	{#if inactiveFields.length > 0}
		<div class="relative flex shrink-0 items-start">
			<Button variant="outline" class="h-auto py-6" onclick={() => (showAddMenu = !showAddMenu)}>
				<Plus class="mr-2 h-4 w-4" />
				Add Filter
			</Button>

			{#if showAddMenu}
				<div
					class="absolute left-0 top-full z-10 mt-1 min-w-48 rounded-md border bg-popover p-1 shadow-lg"
				>
					{#each inactiveFields as { key, field }}
						<button
							class="w-full rounded-sm px-3 py-1.5 text-left text-sm hover:bg-accent"
							onclick={() => addField(key)}
						>
							{field.display}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>
