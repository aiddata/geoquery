<script lang="ts">
	import OptionsSection from './OptionsSection.svelte';

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
		<!-- Radios even for a single measure, so every dataset reads the same -->
		<div role="radiogroup" aria-labelledby="measure-heading" class="flex flex-wrap gap-x-4 gap-y-2">
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
	</OptionsSection>
{/if}
