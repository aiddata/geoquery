<script lang="ts">
	import { type BoundaryResult, type BoundaryPreset } from '$lib/api';
	import { Button } from '$lib/components/ui/button';
	import { ChevronDown, Plus } from '@lucide/svelte';
	import * as Collapsible from '$lib/components/ui/collapsible';

	interface Props {
		allBoundaries?: BoundaryResult[];
		selectedIds?: Set<number>;
		presets?: BoundaryPreset[];
		onSelectionChange?: (ids: Set<number>) => void;
		loading?: boolean;
	}

	let {
		allBoundaries = [],
		selectedIds = new Set(),
		presets = [],
		onSelectionChange,
		loading = false
	}: Props = $props();

	let groupingDimension = $state<'adm_level' | 'source' | 'tags'>('adm_level');

	// Group boundaries by selected dimension
	let groupedBoundaries = $derived.by(() => {
		const groups = new Map<string | number, BoundaryResult[]>();

		if (groupingDimension === 'adm_level') {
			for (const b of allBoundaries) {
				const level = b.group_level !== null ? b.group_level : 'Unspecified';
				if (!groups.has(level)) groups.set(level, []);
				groups.get(level)!.push(b);
			}
		} else if (groupingDimension === 'source') {
			for (const b of allBoundaries) {
				const source = b.source_name || 'Uncategorized';
				if (!groups.has(source)) groups.set(source, []);
				groups.get(source)!.push(b);
			}
		} else if (groupingDimension === 'tags') {
			for (const b of allBoundaries) {
				if (!b.tags || b.tags.length === 0) {
					const key = 'Untagged';
					if (!groups.has(key)) groups.set(key, []);
					groups.get(key)!.push(b);
				} else {
					for (const tag of b.tags) {
						if (!groups.has(tag)) groups.set(tag, []);
						groups.get(tag)!.push(b);
					}
				}
			}
		}

		// Sort groups: ADM level uses numeric order (Unspecified last); others alphabetical
		return new Map(
			[...groups.entries()].sort((a, b) => {
				if (groupingDimension === 'adm_level') {
					const aNum = typeof a[0] === 'number' ? a[0] : Infinity;
					const bNum = typeof b[0] === 'number' ? b[0] : Infinity;
					return aNum - bNum;
				}
				return String(a[0]).toLowerCase().localeCompare(String(b[0]).toLowerCase());
			})
		);
	});

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

	function applyPreset(preset: BoundaryPreset) {
		const matchingIds = allBoundaries
			.filter((b) => {
				if (preset.source_name && b.source_name !== preset.source_name) return false;
				if (preset.group_class && b.group_class !== preset.group_class) return false;
				if (preset.group_level !== undefined && preset.group_level !== null && b.group_level !== preset.group_level) {
					return false;
				}
				if (preset.tags && preset.tags.length > 0) {
					return preset.tags.every((tag) => b.tags?.includes(tag));
				}
				return true;
			})
			.map((b) => b.id);

		const newIds = new Set(selectedIds);
		matchingIds.forEach((id) => newIds.add(id));
		onSelectionChange?.(newIds);
	}
</script>

<div class="space-y-3">
	<!-- Preset buttons -->
	{#if presets.length > 0}
		<div class="flex flex-wrap gap-1">
			{#each presets as preset (preset.sort_order)}
				<Button
					size="xs"
					variant="outline"
					onclick={() => applyPreset(preset)}
					title={preset.description || undefined}
					class="text-xs"
				>
					<Plus class="h-3 w-3 mr-1" />
					{preset.name}
				</Button>
			{/each}
		</div>
	{/if}

	<!-- Grouping dimension buttons -->
	<div class="grid grid-cols-3 gap-1">
		<Button
			size="xs"
			variant={groupingDimension === 'adm_level' ? 'default' : 'outline'}
			onclick={() => (groupingDimension = 'adm_level')}
			class="text-xs"
		>
			ADM Level
		</Button>
		<Button
			size="xs"
			variant={groupingDimension === 'source' ? 'default' : 'outline'}
			onclick={() => (groupingDimension = 'source')}
			class="text-xs"
		>
			Source
		</Button>
		<Button
			size="xs"
			variant={groupingDimension === 'tags' ? 'default' : 'outline'}
			onclick={() => (groupingDimension = 'tags')}
			class="text-xs"
		>
			Tags
		</Button>
	</div>

	<!-- Boundary list -->
	<div class="space-y-1 mt-2">
			{#if loading}
				<div class="text-xs text-muted-foreground py-2">Loading boundaries...</div>
			{:else if allBoundaries.length === 0}
				<div class="text-xs text-muted-foreground py-2">No boundaries found.</div>
			{:else}
				{#each [...groupedBoundaries.entries()] as [groupName, boundaries] (groupName)}
					<Collapsible.Root>
						<div class="flex items-center gap-2">
							<Collapsible.Trigger class="text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
								<ChevronDown class="h-3 w-3" />
							</Collapsible.Trigger>
							<label class="flex-1 flex items-center gap-2 cursor-pointer text-xs font-medium hover:text-foreground">
								<input
									type="checkbox"
									class="rounded h-3.5 w-3.5 cursor-pointer"
									checked={boundaries.every((b) => selectedIds.has(b.id))}
									indeterminate={boundaries.some((b) => selectedIds.has(b.id)) &&
										!boundaries.every((b) => selectedIds.has(b.id))}
									onchange={() => toggleGroup(boundaries.map((b) => b.id))}
								/>
								<span class="truncate">
									{typeof groupName === 'number' ? `Level ${groupName}` : groupName}
									<span class="text-muted-foreground font-normal">({boundaries.length})</span>
								</span>
							</label>
						</div>
						<Collapsible.Content class="pl-5 space-y-1.5 mt-1">
							{#each boundaries as boundary (boundary.id)}
								<label class="flex items-center gap-2 text-xs cursor-pointer hover:text-foreground">
									<input
										type="checkbox"
										class="rounded h-3.5 w-3.5 cursor-pointer"
										checked={selectedIds.has(boundary.id)}
										onchange={() => toggleBoundary(boundary.id)}
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
