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
		onUpdateRequest: () => void;
		onReset: () => void;
	}

	let {
		isFeature,
		saveState,
		onAddToRequest,
		onUpdateRequest,
		onReset
	}: Props = $props();

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

</div>
