<script lang="ts">
	import { CircleAlert } from '@lucide/svelte';

	// Under a required option card's title while nothing in it is chosen
	// (GEO-163); the card itself gets MISSING_CARD's red outline.
	let { text = 'Choose at least one' }: { text?: string } = $props();
</script>

<p class="flex items-center gap-1 text-xs font-bold text-danger-text">
	<CircleAlert class="size-3.5 shrink-0" aria-hidden="true" />
	{text}
</p>
