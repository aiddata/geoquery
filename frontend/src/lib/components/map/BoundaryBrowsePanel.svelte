<script lang="ts">
	import { type BoundaryResult } from '#lib/api.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Checkbox } from '#lib/components/ui/checkbox/index.js';
	import { ChevronDown } from '@lucide/svelte';
	import * as Collapsible from '#lib/components/ui/collapsible/index.js';
	import { groupByLevel, levelLabel } from '#lib/utils/boundaryLevels.js';

	interface Props {
		allBoundaries?: BoundaryResult[];
		selectedIds?: Set<number>;
		onSelectionChange?: (ids: Set<number>) => void;
		loading?: boolean;
	}

	let {
		allBoundaries = [],
		selectedIds = new Set(),
		onSelectionChange,
		loading = false
	}: Props = $props();

	// Attribution for a boundary row. The list is a dense set of checkboxes
	// with no detail view, so the tooltip is where source, licence and
	// citation can be surfaced without burying the names. The licence line is
	// emitted even when unset: GeoQuery redistributes other people's data, and
	// "not recorded" is what tells the user to go and check.
	function attributionTitle(b: BoundaryResult): string {
		const lines = [b.title || b.name];
		if (b.source_name) lines.push(`Source: ${b.source_name}`);
		lines.push(`License: ${b.license ?? 'not recorded — check the source'}`);
		if (b.citation) lines.push(`Cite as: ${b.citation}`);
		return lines.join('\n');
	}

	// Boundary sets grouped by administrative level (the Explore tab's bulk select)
	let groupedBoundaries = $derived(groupByLevel(allBoundaries));

	function toggleBoundary(id: number) {
		const newIds = new Set(selectedIds);
		if (newIds.has(id)) {
			newIds.delete(id);
		} else {
			newIds.add(id);
		}
		onSelectionChange?.(newIds);
	}

	function toggleGroup(boundaryIds: number[]) {
		const newIds = new Set(selectedIds);
		const allSelected = boundaryIds.every((id) => newIds.has(id));

		if (allSelected) {
			boundaryIds.forEach((id) => newIds.delete(id));
		} else {
			boundaryIds.forEach((id) => newIds.add(id));
		}
		onSelectionChange?.(newIds);
	}
</script>

<div class="space-y-3">
	<!-- Boundary list: scrolls on its own so the count below stays in view -->
	<div class="max-h-96 space-y-1 overflow-y-auto pr-1">
			{#if loading}
				<div class="text-xs text-muted-foreground py-2">Loading boundaries...</div>
			{:else if allBoundaries.length === 0}
				<div class="text-xs text-muted-foreground py-2">No boundaries found.</div>
			{:else}
				{#each [...groupedBoundaries.entries()] as [groupName, boundaries] (groupName)}
					<Collapsible.Root>
						<div class="flex items-center gap-2">
							<Collapsible.Trigger>
								{#snippet child({ props })}
									<Button {...props} variant="ghost" size="icon-sm" class="size-6 text-muted-foreground" aria-label="Show boundaries in {levelLabel(groupName)}">
										<ChevronDown class="size-3.5" />
									</Button>
								{/snippet}
							</Collapsible.Trigger>
							<label class="flex-1 flex items-center gap-2 cursor-pointer text-xs font-bold hover:text-foreground">
								<Checkbox
									checked={boundaries.every((b) => selectedIds.has(b.id))}
									indeterminate={boundaries.some((b) => selectedIds.has(b.id)) &&
										!boundaries.every((b) => selectedIds.has(b.id))}
									onCheckedChange={() => toggleGroup(boundaries.map((b) => b.id))}
								/>
								<span class="truncate">
									{levelLabel(groupName)}
									<span class="text-muted-foreground font-normal">({boundaries.length})</span>
								</span>
							</label>
						</div>
						<!-- A large group (e.g. a common tag) scrolls rather than taking over -->
						<Collapsible.Content class="mt-1 max-h-60 space-y-1.5 overflow-y-auto pl-5 pr-1">
							{#each boundaries as boundary (boundary.id)}
								<label
									class="flex items-center gap-2 text-xs cursor-pointer hover:text-foreground"
									title={attributionTitle(boundary)}
								>
									<Checkbox
										checked={selectedIds.has(boundary.id)}
										onCheckedChange={() => toggleBoundary(boundary.id)}
									/>
									<span class="truncate flex-1">{boundary.title || boundary.name}</span>
								</label>
							{/each}
						</Collapsible.Content>
					</Collapsible.Root>
				{/each}
			{/if}
	</div>

	<p class="text-xs text-muted-foreground">
		{selectedIds.size} selected
	</p>
</div>
