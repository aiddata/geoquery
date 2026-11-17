<script lang="ts">
	import OptionsSection from './OptionsSection.svelte';
	import * as Card from '#lib/components/ui/card/index.js';

	interface Props {
		outcomes: Record<string, string>;
		selected: string;
		onSelect: (key: string) => void;
	}

	let { outcomes, selected, onSelect }: Props = $props();

	const entries = $derived(Object.entries(outcomes));
</script>

{#if entries.length > 0}
	<OptionsSection
		id="measure"
		title="Measure"
		summary="What each feature's result measures."
		help="Each feature's result is this measure, worked out from the records that pass the filters. For example, a deaths estimate adds up deaths, an event count adds one for each event, and a coverage share is the part of the feature the matching records cover."
	>
		<!-- The same card as raster measures, with radios: one measure per version -->
		<Card.Root class="w-72 max-w-full gap-2">
			<Card.Header class="pb-0">
				<Card.Title class="text-sm">Measure</Card.Title>
			</Card.Header>
			<Card.Content class="pt-0">
				<div role="radiogroup" aria-labelledby="measure-heading" class="space-y-2">
					{#each entries as [key, label] (key)}
						<label class="flex cursor-pointer items-center gap-2 text-xs">
							<input
								type="radio"
								name="outcome"
								value={key}
								checked={selected === key}
								onchange={() => onSelect(key)}
								class="size-4 accent-primary"
							/>
							{label}
						</label>
					{/each}
				</div>
			</Card.Content>
		</Card.Root>
	</OptionsSection>
{/if}
