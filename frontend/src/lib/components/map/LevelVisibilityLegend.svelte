<script lang="ts">
	import { Checkbox } from '#lib/components/ui/checkbox/index.js';

	// A map legend for a selection spanning several administrative levels
	// (GEO-141): one checkbox per level, as Bulk select names them, to show or
	// hide that level's selected boundary sets on the map. Hiding only affects
	// the map; the sets stay selected.
	interface LevelGroup {
		key: string;
		label: string;
		count: number;
		hidden: boolean;
	}

	interface Props {
		groups: LevelGroup[];
		onToggle: (key: string) => void;
	}

	let { groups, onToggle }: Props = $props();

	const uid = $props.id();
</script>

<section aria-labelledby="{uid}-heading" class="card-surface w-max max-w-64 px-3 py-2.5 text-xs">
	<h2 id="{uid}-heading" class="mb-1.5 font-bold">Show on map</h2>
	<ul class="space-y-1.5">
		{#each groups as group (group.key)}
			<li>
				<label class="flex cursor-pointer items-center gap-2">
					<Checkbox checked={!group.hidden} onCheckedChange={() => onToggle(group.key)} />
					<span class="min-w-0 flex-1 {group.hidden ? 'text-muted-foreground' : ''}">{group.label}</span>
					<span class="tabular-nums text-muted-foreground">
						{group.count}<span class="sr-only"> boundary set{group.count === 1 ? '' : 's'}</span>
					</span>
				</label>
			</li>
		{/each}
	</ul>
</section>
