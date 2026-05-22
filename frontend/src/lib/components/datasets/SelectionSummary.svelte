<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Button } from '$lib/components/ui/button';
	import { Separator } from '$lib/components/ui/separator';
	import { ShoppingCart, RotateCcw } from '@lucide/svelte';
	import type { DatasetDetail } from '$lib/api';

	interface Props {
		dataset: DatasetDetail | null;
		// Release filters
		filters?: Record<string, string[]>;
		// Raster options
		extractTypes?: string[];
		selectedResources?: string[];
		//
		onAddToRequest: (customName: string) => void;
		onReset: () => void;
	}

	let {
		dataset,
		filters,
		extractTypes,
		selectedResources,
		onAddToRequest,
		onReset
	}: Props = $props();

	let customName = $state('');

	let summaryLines = $derived.by(() => {
		if (!dataset) return [];
		const lines: string[] = [];

		lines.push(`Extract data from ${dataset.title ?? dataset.name}`);

		if (dataset.type === 'release' && filters) {
			for (const [key, values] of Object.entries(filters)) {
				if (values.includes('All')) continue;
				const field = dataset.fields[key];
				const display = field?.display ?? key;
				lines.push(`where ${display} includes ${values.join(', ')}`);
			}
		}

		if (dataset.type !== 'release') {
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

	let canAdd = $derived.by(() => {
		if (!dataset) return false;

		if (dataset.type === 'release') {
			// Must have at least one non-"All" filter or any active filters
			return true;
		}

		// Raster: must have at least one extract type selected
		return (extractTypes?.length ?? 0) > 0;
	});
</script>

<div class="flex h-full flex-col">
	<div class="space-y-4 p-4">
		<h3 class="text-sm font-semibold">Selection Summary</h3>

		{#if !dataset}
			<p class="text-sm text-muted-foreground">Select a dataset to begin configuring your query.</p>
		{:else}
			<!-- Custom Name -->
			<div class="space-y-1.5">
				<Label class="text-xs">Selection Name</Label>
				<Input
					bind:value={customName}
					placeholder={dataset.title ?? dataset.name}
					class="h-8 text-xs"
				/>
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
