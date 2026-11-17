<script lang="ts">
	import type { BoundaryResult } from '#lib/api.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Checkbox } from '#lib/components/ui/checkbox/index.js';
	import { groupByLevel, levelLabel, type LevelKey } from '#lib/utils/boundaryLevels.js';

	// After an area is drawn on the map: the boundary sets that intersect it,
	// by administrative level. Ticking levels and adding selects every set at
	// those levels, as if each had been searched for and picked.
	interface Props {
		/** null while they're being looked up */
		matches: BoundaryResult[] | null;
		/** The lookup failed */
		error?: boolean;
		/** Already selected, so they're not counted as added again */
		selectedIds: Set<number>;
		onAdd: (boundaries: BoundaryResult[]) => void;
		onCancel: () => void;
	}

	let { matches, error = false, selectedIds, onAdd, onCancel }: Props = $props();

	const groups = $derived(groupByLevel(matches ?? []));
	let picked = $state(new Set<LevelKey>());

	const toAdd = $derived(
		[...groups.entries()]
			.filter(([level]) => picked.has(level))
			.flatMap(([, sets]) => sets)
			.filter((b) => !selectedIds.has(b.id))
	);

	function toggle(level: LevelKey) {
		const next = new Set(picked);
		if (next.has(level)) next.delete(level);
		else next.add(level);
		picked = next;
	}
</script>

<div class="card-surface w-64 space-y-3 p-3" role="dialog" aria-labelledby="aoi-heading">
	<div>
		<h2 id="aoi-heading" class="text-sm font-bold">Boundaries in this area</h2>
		<p class="text-xs text-muted-foreground" aria-live="polite">
			{#if matches === null}
				Finding boundary sets in this area…
			{:else if error}
				Couldn't look up this area. Try drawing it again.
			{:else if matches.length === 0}
				No boundary sets have features in this area.
			{:else}
				{matches.length === 1 ? '1 boundary set has' : `${matches.length} boundary sets have`} features here. Choose the levels to add.
			{/if}
		</p>
	</div>

	{#if matches && matches.length > 0}
		<ul class="max-h-60 space-y-1 overflow-y-auto">
			{#each [...groups.entries()] as [level, sets] (level)}
				{@const fresh = sets.filter((b) => !selectedIds.has(b.id)).length}
				<li>
					<label
						class="flex cursor-pointer items-center gap-2 rounded-sm px-1 py-1 text-xs hover:bg-accent"
						title={sets.map((b) => b.title || b.name).join('\n')}
					>
						<Checkbox checked={picked.has(level)} disabled={fresh === 0} onCheckedChange={() => toggle(level)} />
						<span class="font-bold">{levelLabel(level)}</span>
						<span class="ml-auto text-muted-foreground tabular-nums">
							{fresh === 0 ? 'all selected' : `${sets.length} set${sets.length === 1 ? '' : 's'}`}
						</span>
					</label>
				</li>
			{/each}
		</ul>
	{/if}

	<div class="flex justify-end gap-2">
		<Button variant="outline" size="sm" onclick={onCancel}>Cancel</Button>
		{#if matches && matches.length > 0}
			<Button size="sm" disabled={toAdd.length === 0} onclick={() => onAdd(toAdd)}>
				{toAdd.length > 0 ? `Add ${toAdd.length} set${toAdd.length === 1 ? '' : 's'}` : 'Add'}
			</Button>
		{/if}
	</div>
</div>
