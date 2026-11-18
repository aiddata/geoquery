<script lang="ts">
	import { LoaderCircle } from '@lucide/svelte';

	interface Props {
		loading: boolean;
		count: number | null;
		error?: boolean;
		/** Inline in a line of text (a step's summary) rather than its own line */
		inline?: boolean;
	}

	let { loading, count, error = false, inline = false }: Props = $props();
</script>

<svelte:element
	this={inline ? 'span' : 'p'}
	class="{inline ? 'inline-flex align-bottom' : 'flex'} items-center gap-1.5 text-xs text-muted-foreground"
	role="status"
	aria-live="polite"
>
	{#if loading}
		<LoaderCircle class="size-3.5 animate-spin" aria-hidden="true" />
		Checking coverage…
	{:else if error}
		<span class="text-destructive">Couldn't check coverage. Please try again.</span>
	{:else if count !== null}
		<span><strong>{count}</strong> dataset{count === 1 ? '' : 's'} available</span>
	{/if}
</svelte:element>
