<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';

	// An icon button for the map's tool column, with its tooltip to the left
	interface Props {
		label: string;
		/** Tooltip text, if it says more than the label */
		tooltip?: string;
		onclick?: () => void;
		/**
		 * Unavailable. Marked aria-disabled rather than disabled, so it can still
		 * be hovered and focused to show the tooltip saying why.
		 */
		disabled?: boolean;
		pressed?: boolean;
		children: Snippet;
	}

	let { label, tooltip, onclick, disabled = false, pressed, children }: Props = $props();
</script>

<Tooltip.Root>
	<Tooltip.Trigger>
		{#snippet child({ props })}
			<Button
				{...props}
				variant={pressed ? 'default' : 'ghost'}
				size="icon"
				aria-label={label}
				aria-pressed={pressed}
				aria-disabled={disabled || undefined}
				class="aria-disabled:pointer-events-auto aria-disabled:cursor-not-allowed aria-disabled:hover:bg-transparent"
				onclick={() => {
					if (!disabled) onclick?.();
				}}
			>
				{@render children()}
			</Button>
		{/snippet}
	</Tooltip.Trigger>
	<Tooltip.Content side="left" sideOffset={6}>
		<p class="text-xs">{tooltip ?? label}</p>
	</Tooltip.Content>
</Tooltip.Root>
