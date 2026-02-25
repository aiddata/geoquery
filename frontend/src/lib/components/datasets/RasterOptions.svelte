<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Label } from '$lib/components/ui/label';
	import { ScrollArea } from '$lib/components/ui/scroll-area';
	import type { DatasetDetail } from '$lib/api';

	interface RasterSelection {
		extractTypes: string[];
		resources: string[]; // resource names
	}

	interface Props {
		dataset: DatasetDetail;
		options: RasterSelection;
		onOptionsChange: (options: RasterSelection) => void;
	}

	let { dataset, options, onOptionsChange }: Props = $props();

	let allExtractsSelected = $derived(
		options.extractTypes.length === dataset.extract_types.length
	);

	let allResourcesSelected = $derived(
		options.resources.length === dataset.resources.length
	);

	let isTemporallyVarying = $derived(
		dataset.temporal_name !== 'Temporally Invariant' && dataset.resources.length > 0
	);

	function toggleExtractType(type: string) {
		const current = options.extractTypes;
		const next = current.includes(type)
			? current.filter((t) => t !== type)
			: [...current, type];
		onOptionsChange({ ...options, extractTypes: next });
	}

	function toggleAllExtracts() {
		if (allExtractsSelected) {
			onOptionsChange({ ...options, extractTypes: [] });
		} else {
			onOptionsChange({ ...options, extractTypes: [...dataset.extract_types] });
		}
	}

	function toggleResource(name: string) {
		const current = options.resources;
		const next = current.includes(name)
			? current.filter((r) => r !== name)
			: [...current, name];
		onOptionsChange({ ...options, resources: next });
	}

	function toggleAllResources() {
		if (allResourcesSelected) {
			onOptionsChange({ ...options, resources: [] });
		} else {
			onOptionsChange({ ...options, resources: dataset.resources.map((r) => r.name) });
		}
	}

	function formatTemporal(dateStr: string | null): string {
		if (!dateStr) return 'Unknown';
		try {
			const d = new Date(dateStr);
			if (dataset.temporal_type === 'year') return String(d.getFullYear());
			if (dataset.temporal_type === 'year month')
				return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short' });
			return d.toLocaleDateString('en-US');
		} catch {
			return dateStr;
		}
	}
</script>

<div class="flex gap-4 p-4">
	<!-- Extract Types Card -->
	<Card.Root class="w-72 shrink-0">
		<Card.Header class="pb-2">
			<Card.Title class="text-sm">
				Extract Options
				<span class="ml-1 text-xs text-muted-foreground">
					({options.extractTypes.length}/{dataset.extract_types.length})
				</span>
			</Card.Title>
		</Card.Header>
		<Card.Content class="pt-0">
			<div class="space-y-2">
				<!-- Select All -->
				<div class="flex items-center gap-2 border-b pb-2">
					<Checkbox
						checked={allExtractsSelected}
						onCheckedChange={toggleAllExtracts}
					/>
					<Label class="text-xs font-medium">All Extract Options</Label>
				</div>

				{#each dataset.extract_types as type}
					<div class="flex items-center gap-2">
						<Checkbox
							checked={options.extractTypes.includes(type)}
							onCheckedChange={() => toggleExtractType(type)}
						/>
						<Label class="text-xs font-normal capitalize">{type}</Label>
					</div>
				{/each}
			</div>
		</Card.Content>
	</Card.Root>

	<!-- Temporal Resources Card (only if temporally varying) -->
	{#if isTemporallyVarying}
		<Card.Root class="w-72 shrink-0">
			<Card.Header class="pb-2">
				<Card.Title class="text-sm">
					Time Periods
					<span class="ml-1 text-xs text-muted-foreground">
						({options.resources.length}/{dataset.resources.length})
					</span>
				</Card.Title>
			</Card.Header>
			<Card.Content class="pt-0">
				<ScrollArea class="h-64">
					<div class="space-y-2 pr-3">
						<!-- Select All -->
						<div class="flex items-center gap-2 border-b pb-2">
							<Checkbox
								checked={allResourcesSelected}
								onCheckedChange={toggleAllResources}
							/>
							<Label class="text-xs font-medium">All Time Periods</Label>
						</div>

						{#each dataset.resources as resource}
							<div class="flex items-center gap-2">
								<Checkbox
									checked={options.resources.includes(resource.name)}
									onCheckedChange={() => toggleResource(resource.name)}
								/>
								<Label class="text-xs font-normal">
									{resource.label ?? formatTemporal(resource.temporal)}
								</Label>
							</div>
						{/each}
					</div>
				</ScrollArea>
			</Card.Content>
		</Card.Root>
	{/if}
</div>
