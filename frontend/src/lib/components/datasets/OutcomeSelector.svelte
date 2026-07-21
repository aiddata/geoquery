<script lang="ts">
	import { Label } from '$lib/components/ui/label';

	interface Props {
		outcomes: Record<string, string>;
		selected: string;
		onSelect: (key: string) => void;
	}

	let { outcomes, selected, onSelect }: Props = $props();

	const entries = $derived(Object.entries(outcomes));
</script>

{#if entries.length > 1}
	<div class="p-4 pb-0">
		<p class="mb-2 text-sm font-medium">Outcome</p>
		<div class="flex flex-wrap gap-3">
			{#each entries as [key, label]}
				{@const isSelected = selected === key}
				<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
				<div
					class="flex cursor-pointer items-center gap-2"
					onclick={() => onSelect(key)}
				>
					<div class="flex h-4 w-4 items-center justify-center rounded-full border-2 {isSelected ? 'border-primary bg-primary' : 'border-muted-foreground'}">
						{#if isSelected}
							<div class="h-1.5 w-1.5 rounded-full bg-white"></div>
						{/if}
					</div>
					<Label class="cursor-pointer text-xs">{label}</Label>
				</div>
			{/each}
		</div>
	</div>
{/if}
