<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { ShoppingCart, RotateCcw, Check, CircleAlert, CircleCheck, Pencil, Plus } from '@lucide/svelte';
	import type { DatasetDetail } from '#lib/api.js';

	// The open dataset's controls, shown in a row beside the "Select Dataset
	// Options" heading: Reset, then Add / Update, then where the options stand.
	interface Props {
		dataset: DatasetDetail;
		/** Feature (filter-and-aggregate) dataset: added with a click, not automatically. */
		isFeature: boolean;
		extractTypes?: string[];
		selectedResources?: string[];
		/**
		 * saved: the current options are in the request.
		 * unsaved: feature dataset whose current filters aren't in the request.
		 * editing: like unsaved, but opened with "Edit options" from Review,
		 *   so Update Request can replace the entry being edited.
		 * incomplete: raster dataset still missing an extract option or period.
		 */
		saveState: 'saved' | 'unsaved' | 'editing' | 'incomplete' | null;
		onAddToRequest: () => void;
		onUpdateRequest: () => void;
		onReset: () => void;
	}

	let {
		dataset,
		isFeature,
		extractTypes = [],
		selectedResources = [],
		saveState,
		onAddToRequest,
		onUpdateRequest,
		onReset
	}: Props = $props();

	// What an incomplete raster still needs: an extract option, and a time
	// period when the dataset has them (as on the Customize page).
	const missing = $derived.by(() => {
		const hasPeriods = dataset.temporal_name !== 'Temporally Invariant' && dataset.resources.length > 0;
		const needsExtract = extractTypes.length === 0;
		const needsPeriod = hasPeriods && selectedResources.length === 0;
		if (needsExtract && needsPeriod) return 'extract option and one time period';
		return needsPeriod ? 'time period' : 'extract option';
	});
</script>

<div class="flex flex-wrap items-center gap-2">
	<Button variant="outline" size="sm" onclick={onReset}>
		<RotateCcw />
		Reset
	</Button>

	{#if isFeature && saveState === 'editing'}
		<Button size="sm" onclick={onUpdateRequest}>
			<Pencil />
			Update Request
		</Button>
		<Button variant="outline" size="sm" onclick={onAddToRequest}>
			<Plus />
			Add as New Version
		</Button>
	{:else if isFeature && saveState === 'unsaved'}
		<Button size="sm" onclick={onAddToRequest}>
			<ShoppingCart />
			Add to Request
		</Button>
	{:else}
		<!-- Rasters are added automatically, and feature filters already in the
		     request don't need adding again: shown, but not clickable. -->
		<Button size="sm" disabled>
			{#if saveState === 'saved'}
				<Check />
				Added to Request
			{:else}
				<ShoppingCart />
				Add to Request
			{/if}
		</Button>
	{/if}

	<p class="flex min-w-0 items-start gap-1.5 text-xs text-muted-foreground" role="status">
		{#if saveState === 'saved'}
			<CircleCheck class="size-4 shrink-0 text-success-text" aria-hidden="true" />
			<span>
				<strong class="text-foreground">In your request.</strong>
				{isFeature
					? 'Change the filters to add another version.'
					: 'Changes are saved automatically; Reset removes it.'}
			</span>
		{:else if saveState === 'unsaved'}
			<CircleAlert class="size-4 shrink-0 text-warning-text" aria-hidden="true" />
			<span>
				<strong class="text-foreground">Not added yet.</strong> These filters are saved, but they're
				only in your request once you add them.
			</span>
		{:else if saveState === 'editing'}
			<CircleAlert class="size-4 shrink-0 text-warning-text" aria-hidden="true" />
			<span>
				<strong class="text-foreground">Editing a version in your request.</strong> Update it, or add
				these filters as a new version.
			</span>
		{:else if saveState === 'incomplete'}
			<span>Choose at least one {missing} to add this dataset to your request.</span>
		{/if}
	</p>
</div>
