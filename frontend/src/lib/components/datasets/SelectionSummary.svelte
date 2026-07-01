<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Button } from '$lib/components/ui/button';
	import { Separator } from '$lib/components/ui/separator';
	import { ShoppingCart, RotateCcw } from '@lucide/svelte';
	import type { DatasetDetail } from '$lib/api';
	import type { FilterSelection } from '$lib/stores/cart';

	interface Props {
		dataset: DatasetDetail | null;
		extractTypes?: string[];
		selectedResources?: string[];
		filterSelections?: Record<string, FilterSelection>;
		onAddToRequest: (customName: string) => void;
		onReset: () => void;
	}

	let {
		dataset,
		extractTypes,
		selectedResources,
		filterSelections,
		onAddToRequest,
		onReset
	}: Props = $props();

	let customName = $state('');

	let summaryLines = $derived.by(() => {
		if (!dataset) return [];
		const lines: string[] = [];

		lines.push(`Extract data from ${dataset.title ?? dataset.name}`);

		if (filterSelections) {
			const parts = Object.entries(filterSelections).map(([key, sel]) => {
				if (sel.type === 'range') return `${key}: ${sel.start}–${sel.end}`;
				return `${key}: ${sel.selected.length} selected`;
			});
			if (parts.length) lines.push(`with filters: ${parts.join('; ')}`);
		} else {
			if (extractTypes && extractTypes.length > 0) {
				lines.push(`calculating ${extractTypes.join(', ')}`);
			}
			if (selectedResources && selectedResources.length > 0) {
				const resourceLabels = selectedResources.map((name) => {
					const r = dataset.resources.find((res) => res.name === name);
					return r?.label ?? name;
				});
				lines.push(`for ${resourceLabels.join(', ')}`);
			}
		}

		return lines;
	});

	let canAdd = $derived(!!dataset && (filterSelections !== undefined || (extractTypes?.length ?? 0) > 0));
</script>

<div class="flex h-full flex-col">
	<div class="min-h-0 flex-1 overflow-y-auto space-y-4 p-4">
		<h3 class="text-sm font-semibold">Selection Summary</h3>

		{#if !dataset}
			<p class="text-sm text-muted-foreground">Select a dataset to begin configuring your query.</p>
		{:else}
			<!-- FLAG: restore the Input below (and remove the <p>) to allow custom name editing -->
			<!-- Custom Name -->
			<div class="space-y-1.5">
				<Label class="text-xs">Selection Name</Label>
				<p class="text-xs text-muted-foreground">{dataset.title ?? dataset.name}</p>
				<!-- <Input
					bind:value={customName}
					placeholder={dataset.title ?? dataset.name}
					class="h-8 text-xs"
				/> -->
			</div>

			<Separator />

			<!-- Query Summary -->
			<Card.Root>
				<Card.Content class="p-3">
					<div class="space-y-1 text-xs">
						{#each summaryLines as line}
							<p class="text-muted-foreground">{line}</p>
						{/each}
					</div>
				</Card.Content>
			</Card.Root>
		{/if}
	</div>

	<!-- Actions pinned to bottom -->
	{#if dataset}
		<div class="mt-auto space-y-2 border-t p-4">
			<Button class="w-full" disabled={!canAdd} onclick={() => onAddToRequest(customName)}>
				<ShoppingCart class="mr-2 h-4 w-4" />
				Add to Request
			</Button>
			<Button variant="outline" class="w-full" onclick={onReset}>
				<RotateCcw class="mr-2 h-4 w-4" />
				Reset
			</Button>
		</div>
	{/if}
</div>
