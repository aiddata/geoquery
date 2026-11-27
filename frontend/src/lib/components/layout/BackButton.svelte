<script lang="ts">
	import { page } from '$app/state';
	import { Button } from '#lib/components/ui/button/index.js';
	import { ArrowLeft } from '@lucide/svelte';
	import { goBack } from '#lib/backNav.js';

	interface Props {
		/** Where Back goes when the page wasn't opened from elsewhere in the app */
		fallback?: string;
	}

	let { fallback = '/' }: Props = $props();
</script>

<!-- Back to the page this one was opened from (lib/backNav.ts) -->
<Button variant="ghost" onclick={() => goBack(page.route.id, fallback)}>
	<ArrowLeft />
	Back
</Button>
