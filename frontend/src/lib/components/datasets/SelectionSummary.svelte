<script lang="ts">
	import * as Card from '#lib/components/ui/card/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Separator } from '#lib/components/ui/separator/index.js';
	import { ShoppingCart, RotateCcw, Check, CircleAlert, CircleCheck, Pencil, Plus } from '@lucide/svelte';
	import type { DatasetDetail } from '#lib/api.js';
	import type { FilterSelection } from '#lib/stores/cart.js';

	interface Props {
		dataset: DatasetDetail | null;
		extractTypes?: string[];
		selectedResources?: string[];
		filterSelections?: Record<string, FilterSelection>;
		/** Feature datasets only: rasters are added as their options change. */
		onAddToRequest: () => void;
		/** Feature datasets opened with "Edit options": replace that entry. */
		onUpdateRequest?: () => void;
		onReset: () => void;
		/**
		 * saved: the current options are in the request.
		 * unsaved: feature dataset whose current filters aren't in the request.
		 * editing: like unsaved, but opened with "Edit options" from Review,
		 *   so Update Request can replace the entry being edited.
		 * incomplete: raster dataset with no extract option chosen yet.
		 */
		saveState?: 'saved' | 'unsaved' | 'editing' | 'incomplete' | null;
	}

	let {
		dataset,
		extractTypes,
		selectedResources,
		filterSelections,
		onAddToRequest,
		onUpdateRequest,
		onReset,
		saveState = null
	}: Props = $props();

	const isFeature = $derived(filterSelections !== undefined);

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

</script>

<div class="flex h-full flex-col">
	<div class="min-h-0 flex-1 overflow-y-auto space-y-4 p-4">
		<h3 class="text-sm">Selection Summary</h3>

		{#if !dataset}
			<p class="text-sm text-muted-foreground">Select a dataset to begin configuring your query.</p>
			<p class="text-xs text-muted-foreground">
				Raster datasets join your request as soon as you choose their options. Feature datasets
				need <strong>Add to Request</strong>, and can be added more than once with different filters.
			</p>
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
			{#if saveState === 'saved'}
				<p class="flex items-start gap-2 text-xs text-muted-foreground" role="status">
					<CircleCheck class="mt-px size-4 shrink-0 text-success-text" aria-hidden="true" />
					<span>
						<strong class="text-foreground">In your request.</strong>
						{isFeature
							? 'Change the filters to add another version of this dataset.'
							: 'Changes are saved automatically. Reset removes it from your request.'}
					</span>
				</p>
			{:else if saveState === 'unsaved'}
				<p class="flex items-start gap-2 text-xs text-muted-foreground" role="status">
					<CircleAlert class="mt-px size-4 shrink-0 text-warning-text" aria-hidden="true" />
					<span>
						<strong class="text-foreground">Not added yet.</strong> These filters are saved, but
						they're only in your request once you click Add to Request.
					</span>
				</p>
			{:else if saveState === 'editing'}
				<p class="flex items-start gap-2 text-xs text-muted-foreground" role="status">
					<CircleAlert class="mt-px size-4 shrink-0 text-warning-text" aria-hidden="true" />
					<span>
						<strong class="text-foreground">Editing a version in your request.</strong> Update it with
						these filters, or keep it and add these as a new version.
					</span>
				</p>
			{:else if saveState === 'incomplete'}
				<p class="text-xs text-muted-foreground" role="status">
					Choose at least one extract option to add this dataset to your request.
				</p>
			{/if}
			{#if isFeature && saveState === 'editing'}
				<Button class="w-full" onclick={onUpdateRequest}>
					<Pencil />
					Update Request
				</Button>
				<Button variant="outline" class="w-full" onclick={onAddToRequest}>
					<Plus />
					Add as New Version
				</Button>
			{:else if isFeature && saveState === 'unsaved'}
				<Button class="w-full" onclick={onAddToRequest}>
					<ShoppingCart />
					Add to Request
				</Button>
			{:else}
				<!-- Rasters are added automatically, and feature filters already in
				     the request don't need adding again: shown, but not clickable. -->
				<Button class="w-full" disabled>
					{#if saveState === 'saved'}
						<Check />
						Added to Request
					{:else}
						<ShoppingCart />
						Add to Request
					{/if}
				</Button>
			{/if}
			<Button variant="outline" class="w-full" onclick={onReset}>
				<RotateCcw />
				Reset
			</Button>
		</div>
	{/if}
</div>
