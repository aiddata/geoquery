<script lang="ts">
	import { ArrowLeft, Check } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { closeDetail } from '#lib/stepDetail.js';

	// The way back from a step's detail view to its panel, on narrow screens
	// only (lib/stepDetail.ts): wider screens show both.
	interface Props {
		label: string;
		/** Finished with the detail (e.g. the dataset is in the request): a check, not an arrow */
		done?: boolean;
		class?: string;
	}

	let { label, done = false, class: className = '' }: Props = $props();
</script>

<Button variant="outline" size="sm" class="bg-card md:hidden {className}" onclick={closeDetail}>
	{#if done}<Check />{:else}<ArrowLeft />{/if}
	{label}
</Button>
