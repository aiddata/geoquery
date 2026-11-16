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
		summary="The value added up for each area."
		help="Each area's result is the total of this value across the records that pass the filters. For example, a deaths estimate adds up deaths, while an event count adds one for each event."
	>
		{#if entries.length === 1}
			<p class="text-xs font-bold">{entries[0][1]}</p>
		{:else}
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
		{/if}
	</OptionsSection>
{/if}
