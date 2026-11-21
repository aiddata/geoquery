<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { RotateCcw } from '@lucide/svelte';

	// The open dataset's Reset, beside the "Select Dataset Options" heading.
	// Options save as they change for every dataset (GEO-153), so there's
	// nothing to add; where they stand is in the output summary.
	interface Props {
		/** Feature (filter-and-aggregate) dataset: resets the selection being edited */
		isFeature: boolean;
		onReset: () => void;
		/** Something differs from the dataset's starting options, so Reset has work to do */
		canReset?: boolean;
	}

	let { isFeature, onReset, canReset = true }: Props = $props();
</script>

<!-- Only ever this dataset: a raster's options (and its entry in the request),
     or the feature selection being edited (other selections stay). Hidden
     while there's nothing to reset (GEO-162). -->
{#if canReset}
	<Button
		variant="outline"
		size="sm"
		onclick={onReset}
		title={isFeature
			? 'Clear this selection’s options, which takes it out of your request. Other selections, and other datasets, are kept.'
			: 'Clear this dataset’s options and remove it from your request. Other datasets are kept.'}
	>
		<RotateCcw />
		{isFeature ? 'Reset selection' : 'Reset this dataset'}
	</Button>
{/if}
