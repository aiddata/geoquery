<script lang="ts">
	import * as Card from '#lib/components/ui/card/index.js';
	import { Checkbox } from '#lib/components/ui/checkbox/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { ScrollArea } from '#lib/components/ui/scroll-area/index.js';
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';
	import type { DatasetDetail, ExtractType } from '#lib/api.js';
	import { Info } from '@lucide/svelte';
	import OptionsSection from './OptionsSection.svelte';
	import { MISSING_CARD, SPLIT_HELP, SPLIT_SUMMARY } from './optionsHelp.js';
	import MissingNote from './MissingNote.svelte';
	import { parseMeasure } from '#lib/utils/measures.js';
	import { formatPeriod, periodRange } from '#lib/utils/periods.js';

	interface RasterSelection {
		extractTypes: string[];
		resources: string[]; // resource names
	}

	interface Props {
		dataset: DatasetDetail;
		options: RasterSelection;
		onOptionsChange: (options: RasterSelection) => void;
		/** Required cards with nothing chosen, to mark (GEO-163) */
		missing?: { measure: boolean; periods: boolean };
	}

	let { dataset, options, onOptionsChange, missing = { measure: false, periods: false } }: Props = $props();

	let lastClickedResourceIndex = $state<number | null>(null);

	let allExtractsSelected = $derived(
		options.extractTypes.length === dataset.extract_types.length
	);

	let allResourcesSelected = $derived(
		options.resources.length === dataset.resources.length
	);

	let isTemporallyVarying = $derived(
		dataset.temporal_name !== 'Temporally Invariant' && dataset.resources.length > 0
	);

	function toggleExtractType(type: ExtractType) {
		const current = options.extractTypes;
		const next = current.includes(type.short_name)
			? current.filter((t) => t !== type.short_name)
			: [...current, type.short_name];
		onOptionsChange({ ...options, extractTypes: next });
	}

	function toggleAllExtracts() {
		if (allExtractsSelected) {
			onOptionsChange({ ...options, extractTypes: [] });
		} else {
			onOptionsChange({ ...options, extractTypes: dataset.extract_types.map((t) => t.short_name) });
		}
	}

	function toggleResource(name: string, index: number, event?: MouseEvent) {
		const current = options.resources;
		const adding = !current.includes(name);

		if (event?.shiftKey && lastClickedResourceIndex !== null) {
			const lo = Math.min(lastClickedResourceIndex, index);
			const hi = Math.max(lastClickedResourceIndex, index);
			const rangeNames = dataset.resources.slice(lo, hi + 1).map((r) => r.name);
			const next = adding
				? [...new Set([...current, ...rangeNames])]
				: current.filter((r) => !rangeNames.includes(r));
			onOptionsChange({ ...options, resources: next });
		} else {
			const next = adding ? [...current, name] : current.filter((r) => r !== name);
			onOptionsChange({ ...options, resources: next });
		}

		lastClickedResourceIndex = index;
	}

	function toggleAllResources() {
		lastClickedResourceIndex = null;
		if (allResourcesSelected) {
			onOptionsChange({ ...options, resources: [] });
		} else {
			onOptionsChange({ ...options, resources: dataset.resources.map((r) => r.name) });
		}
	}

	// Columns per feature: one per selected measure and time period, as the
	// feature datasets' split pill counts them
	const periodColumns = $derived(options.extractTypes.length * options.resources.length);

	// Each option's label and explanation, from its description
	const measures = $derived(
		dataset.extract_types.map((type) => ({ type, ...parseMeasure(type.short_name, type.description) }))
	);

	/** A period as people read it: "1995 January" rather than "199501" (GEO-161) */
	const periodLabel = (resource: DatasetDetail['resources'][number]) =>
		resource.label ? formatPeriod(resource.label) : formatTemporal(resource.temporal);
	// The span "All time periods" covers, e.g. 1992–2013
	const allRange = $derived(periodRange(dataset.resources.map((r) => r.label ?? formatTemporal(r.temporal))));

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

<!-- Measure first, then time periods: one section each, as for feature datasets -->
<div class="mt-4 space-y-4 pb-4">
	<OptionsSection
		id="measure"
		title="Measure"
		summary="What each feature's result measures. Choose one or more."
		help="Each measure summarises the dataset's values within each feature, for example their average or highest value. Every measure you choose adds a column for each time period."
	>
		<Card.Root class="w-72 max-w-full gap-2 {missing.measure ? MISSING_CARD : ''}">
			<Card.Header class="pb-0">
				<Card.Title class="text-sm">
					Measures
					<span class="ml-1 text-xs text-muted-foreground">
						({options.extractTypes.length}/{dataset.extract_types.length})
					</span>
				</Card.Title>
				{#if missing.measure}<MissingNote />{/if}
			</Card.Header>
			<Card.Content class="space-y-2 pt-0">
			<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
			<div class="flex cursor-pointer items-center gap-2 border-b pb-2" onclick={toggleAllExtracts}>
				<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
				<span onclick={(e) => e.stopPropagation()}>
					<Checkbox checked={allExtractsSelected} onCheckedChange={toggleAllExtracts} aria-label="All measures" />
				</span>
				<Label class="cursor-pointer text-xs font-bold">All measures</Label>
			</div>
			{#each measures as { type, label, detail } (type.short_name)}
				<div class="flex items-center gap-2">
					<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
					<div class="flex cursor-pointer items-center gap-2" onclick={() => toggleExtractType(type)}>
						<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
						<span onclick={(e) => e.stopPropagation()}>
							<Checkbox
								checked={options.extractTypes.includes(type.short_name)}
								onCheckedChange={() => toggleExtractType(type)}
								aria-label={label}
								value={type.short_name}
							/>
						</span>
						<Label class="cursor-pointer text-xs font-normal">{label}</Label>
					</div>
					{#if detail}
						<Tooltip.Provider>
							<Tooltip.Root>
								<Tooltip.Trigger
									class="rounded-full text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
									aria-label="About {label}"
								>
									<Info class="size-3.5" aria-hidden="true" />
								</Tooltip.Trigger>
								<Tooltip.Content>
									<p class="max-w-64 text-xs">{detail}</p>
								</Tooltip.Content>
							</Tooltip.Root>
						</Tooltip.Provider>
					{/if}
				</div>
			{/each}
			</Card.Content>
		</Card.Root>
	</OptionsSection>

	{#if isTemporallyVarying}
		<OptionsSection
			id="periods"
			title="Split results by"
			summary={SPLIT_SUMMARY}
			help={SPLIT_HELP}
			note="{periodColumns} column{periodColumns === 1 ? '' : 's'} per feature"
		>
			<Card.Root class="w-72 max-w-full gap-2 {missing.periods ? MISSING_CARD : ''}">
				<Card.Header class="pb-0">
					<Card.Title class="text-sm">
						Time Periods
						<span class="ml-1 text-xs text-muted-foreground">
							({options.resources.length}/{dataset.resources.length})
						</span>
					</Card.Title>
					{#if missing.periods}<MissingNote />{/if}
				</Card.Header>
				<Card.Content class="pt-0">
				<ScrollArea class="h-64">
					<div class="space-y-2 pr-3">
						<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
						<div class="flex cursor-pointer items-center gap-2 border-b pb-2" onclick={toggleAllResources}>
							<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
							<span onclick={(e) => e.stopPropagation()}>
								<Checkbox checked={allResourcesSelected} onCheckedChange={toggleAllResources} aria-label="All time periods" />
							</span>
							<Label class="cursor-pointer text-xs font-bold">
								All time periods
								{#if allRange}<span class="font-normal text-muted-foreground">({allRange})</span>{/if}
							</Label>
						</div>

						{#each dataset.resources as resource, i}
							<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
							<div class="flex cursor-pointer items-center gap-2" onclick={(e) => toggleResource(resource.name, i, e)}>
								<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
								<span onclick={(e) => { e.stopPropagation(); toggleResource(resource.name, i); }}>
									<Checkbox
										checked={options.resources.includes(resource.name)}
										onCheckedChange={() => {}}
										aria-label={periodLabel(resource)}
									/>
								</span>
								<Label class="cursor-pointer select-none text-xs font-normal">
									{periodLabel(resource)}
								</Label>
							</div>
						{/each}
					</div>
				</ScrollArea>
				</Card.Content>
			</Card.Root>
		</OptionsSection>
	{/if}
</div>
