<script lang="ts">
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';
	import CoveragePie from './CoveragePie.svelte';

	// A dataset that covers only some of the selected boundary sets (GEO-127):
	// a partly filled circle, with the count and the shorter of the covered and
	// uncovered lists in its tooltip. Full coverage has no chip.
	interface BoundarySet {
		id: number;
		title: string;
	}

	interface Props {
		/** Every selected boundary set */
		sets: BoundarySet[];
		/** Ids of the selected sets this dataset covers */
		covered: number[];
	}

	let { sets, covered }: Props = $props();

	const list = new Intl.ListFormat('en', { type: 'conjunction' });

	const coveredSet = $derived(new Set(covered));
	const yes = $derived(sets.filter((s) => coveredSet.has(s.id)));
	const no = $derived(sets.filter((s) => !coveredSet.has(s.id)));
	const count = $derived(`Covers ${yes.length} of ${sets.length} selected boundary sets`);
	// Whichever list is shorter; on a tie, the uncovered sets explain the empty rows
	const detail = $derived(
		yes.length < no.length
			? `Only ${list.format(yes.map((s) => s.title))}`
			: `Not ${list.format(no.map((s) => s.title))}`
	);
</script>

<Tooltip.Root>
	<Tooltip.Trigger
		class="flex size-6 items-center justify-center rounded-full text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
		aria-label="{count}. {detail}"
	>
		<CoveragePie fraction={yes.length / sets.length} />
	</Tooltip.Trigger>
	<Tooltip.Content side="right">
		<p class="max-w-64 text-xs font-bold">{count}</p>
		<p class="max-w-64 text-xs">{detail}</p>
	</Tooltip.Content>
</Tooltip.Root>
