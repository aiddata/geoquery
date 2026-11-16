<script lang="ts">
	import type { Snippet } from 'svelte';
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';
	import { Info } from '@lucide/svelte';

	// One labelled group of a feature dataset's options (Measure, Split results
	// by, Filter records): a heading with an info tooltip, a one-line summary of
	// what the group does, then its controls.
	interface Props {
		id: string;
		title: string;
		/** One line under the heading saying what these options do. */
		summary: string;
		/** Longer explanation, shown from the info icon. */
		help: string;
		/** Short note beside the heading, e.g. how many columns a split makes. */
		note?: string;
		children: Snippet;
	}

	let { id, title, summary, help, note, children }: Props = $props();
</script>

<section aria-labelledby="{id}-heading" class="space-y-3 border-t px-4 pt-4 first:border-t-0">
	<div>
		<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
			<h4 id="{id}-heading" class="text-sm font-bold">{title}</h4>
			<Tooltip.Provider>
				<Tooltip.Root>
					<Tooltip.Trigger
						class="rounded-full text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
						aria-label="About {title}"
					>
						<Info class="size-3.5" aria-hidden="true" />
					</Tooltip.Trigger>
					<Tooltip.Content>
						<p class="max-w-72 text-xs">{help}</p>
					</Tooltip.Content>
				</Tooltip.Root>
			</Tooltip.Provider>
			{#if note}
				<span class="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground tabular-nums">{note}</span>
			{/if}
		</div>
		<p class="mt-0.5 text-xs text-muted-foreground">{summary}</p>
	</div>
	{@render children()}
</section>
