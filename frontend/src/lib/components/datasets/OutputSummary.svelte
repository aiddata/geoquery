<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { DatasetDetail } from '#lib/api.js';
	import type { FilterSelection } from '#lib/stores/cart.js';
	import { CircleAlert, CircleCheck } from '@lucide/svelte';
	import { parseMeasure } from '#lib/utils/measures.js';
	import { periodUnit } from '#lib/utils/periods.js';

	// Where the open dataset's options stand, in one line under "Select Dataset
	// Options" (GEO-164): added (and what that adds), or what's still missing.
	// Options join the request on their own (GEO-153), so this is their status.
	// The dataset's Reset sits at the end of the box.
	interface Props {
		dataset: DatasetDetail;
		isFeature: boolean;
		/** Raster options */
		extractTypes?: string[];
		resources?: string[];
		/** Feature-dataset options */
		filterSelections?: Record<string, FilterSelection>;
		outcome?: string;
		saveState?: 'saved' | 'incomplete' | 'duplicate' | null;
		/** A feature selection's required options still to choose, e.g. "a measure" (GEO-163) */
		featureMissingText?: string | null;
		/** The selection that already has exactly these options */
		duplicateOf?: string | null;
		/** At the end of the box: Reset */
		actions?: Snippet;
	}

	let {
		dataset,
		isFeature,
		extractTypes = [],
		resources = [],
		filterSelections = {},
		outcome = '',
		saveState = null,
		featureMissingText = null,
		duplicateOf = null,
		actions
	}: Props = $props();

	const n = (v: number) => v.toLocaleString();
	const plural = (v: number, one: string, many = `${one}s`) => `${n(v)} ${v === 1 ? one : many}`;
	const listLabels = (labels: string[]) =>
		labels.length <= 2 ? labels.join(' and ') : `${labels.slice(0, -1).join(', ')} and ${labels.at(-1)}`;
	const measureLabel = (shortName: string) =>
		parseMeasure(shortName, dataset.extract_types.find((t) => t.short_name === shortName)?.description).label;

	const hasPeriods = $derived(dataset.temporal_name !== 'Temporally Invariant' && dataset.resources.length > 0);
	// "year", "month" or "time period", from the dataset's periods
	const unit = $derived(periodUnit(dataset.resources.map((r) => r.label ?? r.name)));

	// Rasters: one column per measure per period
	const raster = $derived.by(() => {
		const periods = hasPeriods ? resources.length : 1;
		const measures = extractTypes.length > 2 ? plural(extractTypes.length, 'measure') : listLabels(extractTypes.map(measureLabel));
		return {
			columns: extractTypes.length * periods,
			basis: measures + (hasPeriods ? ` across ${plural(periods, unit[0], unit[1])}` : ''),
			missing: [extractTypes.length === 0 ? 'measure' : null, hasPeriods && resources.length === 0 ? unit[0] : null]
				.filter(Boolean)
				.join(' and ')
		};
	});

	// Feature selections: split fields multiply the columns; filters narrow the records
	const feature = $derived.by(() => {
		let columns = 1;
		const splits: string[] = [];
		let narrowed = 0;
		for (const [key, f] of Object.entries(dataset.filters ?? {})) {
			const sel = filterSelections[key];
			if (f.aggregate === false) {
				const count = f.type === 'categorical' && sel?.type === 'categorical' ? sel.selected.length : 1;
				columns *= count;
				splits.push(f.display ?? key);
			} else if (sel?.type === 'categorical' && f.type === 'categorical') {
				if (sel.selected.length < f.categories.length) narrowed++;
			} else if (sel?.type === 'range' && f.type === 'range') {
				if (sel.start > f.min || sel.end < f.max) narrowed++;
			}
		}
		const measure = dataset.outcomes?.[outcome] ?? null;
		return {
			columns,
			// "of Fatalities, by Year, with 1 filter"
			tail:
				(measure ? ` of ${measure}` : '') +
				(splits.length ? ` by ${listLabels(splits)}` : '') +
				(narrowed ? `, with ${plural(narrowed, 'filter')}` : '')
		};
	});

	const ok = $derived(saveState === 'saved');
</script>

<section
	aria-label="Options status"
	class="mx-4 mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border bg-muted/40 px-3 py-2.5 text-sm"
>
	<p class="flex min-w-0 flex-1 items-center gap-2" role="status">
		{#if ok}
			<CircleCheck class="size-5 shrink-0 text-success-text" aria-hidden="true" />
		{:else}
			<CircleAlert class="size-5 shrink-0 text-warning-text" aria-hidden="true" />
		{/if}
		<span class="min-w-0">
			{#if !isFeature}
				{#if raster.missing}
					<strong>Options missing.</strong> Add at least one {raster.missing}.
				{:else}
					<strong>Dataset added.</strong> {plural(raster.columns, 'column')} based on {raster.basis}.
				{/if}
			{:else if saveState === 'duplicate'}
				<strong>Same as “{duplicateOf}”.</strong> Change an option to make this selection different.
			{:else if saveState === 'incomplete'}
				<strong>Options missing.</strong> Add {featureMissingText ?? 'the required options'}.
			{:else}
				<strong>Selection added.</strong> {plural(feature.columns, 'column')}{feature.tail}.
			{/if}
		</span>
	</p>
	{@render actions?.()}
</section>
