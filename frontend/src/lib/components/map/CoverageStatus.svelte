<script lang="ts">
	import { LoaderCircle } from '@lucide/svelte';

	interface Props {
		loading: boolean;
		count: number | null;
		error?: boolean;
	}

	let { loading, count, error = false }: Props = $props();
</script>

<p class="flex items-center gap-1.5 text-xs text-muted-foreground" role="status" aria-live="polite">
	{#if loading}
		<LoaderCircle class="size-3.5 animate-spin" aria-hidden="true" />
		Checking coverage…
	{:else if error}
		<span class="text-destructive">Couldn't check coverage. Please try again.</span>
	{:else if count !== null}
		<span><strong>{count}</strong> dataset{count === 1 ? '' : 's'} available</span>
	{/if}
</p>
