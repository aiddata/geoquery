<script lang="ts">
	import { X } from '@lucide/svelte';

	// A small × at the right end of a search box, shown while it has text.
	// Its parent is the box's `relative` wrapper; give the input right padding
	// (pr-8) so text doesn't run under it.
	interface Props {
		value: string;
		onClear: () => void;
		label?: string;
	}

	let { value, onClear, label = 'Clear search' }: Props = $props();
</script>

{#if value}
	<button
		type="button"
		class="absolute right-1.5 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
		aria-label={label}
		onmousedown={(e) => e.preventDefault()}
		onclick={onClear}
	>
		<X class="size-3.5" aria-hidden="true" />
	</button>
{/if}
