<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { ShoppingCart, RotateCcw, Check, Pencil, Plus } from '@lucide/svelte';

	// The open dataset's controls, in a row beside the "Select Dataset Options"
	// heading: Reset, then (feature datasets) Add / Update. Where the options
	// stand is shown in the output summary above.
	interface Props {
		/** Feature (filter-and-aggregate) dataset: added with a click, not automatically. */
		isFeature: boolean;
		/**
		 * saved: the current options are in the request.
		 * unsaved: feature dataset whose current filters aren't in the request.
		 * editing: like unsaved, but opened with "Edit options" from Review,
		 *   so Update Request can replace the entry being edited.
		 * incomplete: raster dataset still missing an extract option or period.
		 */
		saveState: 'saved' | 'unsaved' | 'editing' | 'incomplete' | null;
		onAddToRequest: () => void;
		/** Name of the version adding would merge into (it only adds values to a split) */
		mergeInto?: string | null;
		onUpdateRequest: () => void;
		onReset: () => void;
		/** Something differs from the dataset's starting options, so Reset has work to do */
		canReset?: boolean;
	}

	let {
		isFeature,
		saveState,
		onAddToRequest,
		mergeInto = null,
		onUpdateRequest,
		onReset,
		canReset = true
	}: Props = $props();

</script>

<div class="flex flex-wrap items-center gap-2">
	<!-- Only ever this dataset: a raster's options (and its entry in the request),
	     or a feature dataset's measure, split and filter options on screen (its
	     versions stay). Hidden while there's nothing to reset. -->
	{#if canReset}
	<Button
		variant="outline"
		size="sm"
		onclick={onReset}
		title={isFeature
			? 'Put the measure, split and filter options shown here back to their defaults. Versions already in your request, and other datasets, are kept.'
			: 'Clear this dataset’s options and remove it from your request. Other datasets are kept.'}
	>
		<RotateCcw />
		{isFeature ? 'Reset options' : 'Reset this dataset'}
	</Button>
	{/if}

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
	{:else if isFeature}
		<!-- Feature filters already in the request don't need adding again:
		     shown, but not clickable. Rasters have no button: they're added
		     automatically, and their status is in the output summary. -->
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

	{#if isFeature && mergeInto && (saveState === 'unsaved' || saveState === 'editing')}
		<p class="text-xs text-muted-foreground">Adds these values to the existing version “{mergeInto}”</p>
	{/if}
</div>
