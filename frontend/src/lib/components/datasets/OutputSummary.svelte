<script lang="ts">
	import type { DatasetDetail } from '#lib/api.js';
	import type { FilterSelection } from '#lib/stores/cart.js';
	import { CircleAlert, CircleCheck } from '@lucide/svelte';
	import { parseMeasure } from '#lib/utils/measures.js';
	import { periodUnit } from '#lib/utils/periods.js';

	// One or two sentences tying the boundary selection to the open dataset's
	// options: how many features, and what the output will hold for each.
	interface Props {
		dataset: DatasetDetail;
		isFeature: boolean;
		features: number;
		boundaries: number;
		/** Raster options */
		extractTypes?: string[];
		resources?: string[];
		/** Feature-dataset options */
		filterSelections?: Record<string, FilterSelection>;
		outcome?: string;
		/** Where the options stand (see DatasetActions / Customize) */
		saveState?: 'saved' | 'unsaved' | 'editing' | 'incomplete' | null;
		/** Nothing from this dataset is in the request yet */
		empty?: boolean;
		/** A feature dataset's required options still to choose, e.g. "a measure" (GEO-163) */
		featureMissingText?: string | null;
	}

	let {
		dataset,
		isFeature,
		features,
		boundaries,
		extractTypes = [],
		resources = [],
		filterSelections = {},
		outcome = '',
		saveState = null,
		empty = false,
		featureMissingText = null
	}: Props = $props();

	// Rasters join the request on their own, so their status lives here (feature
	// datasets keep theirs beside Add to Request): what's still missing, or that
	// the options are in the request.
	const missing = $derived.by(() => {
		const hasPeriods = dataset.temporal_name !== 'Temporally Invariant' && dataset.resources.length > 0;
		const needsExtract = extractTypes.length === 0;
		const needsPeriod = hasPeriods && resources.length === 0;
		if (needsExtract && needsPeriod) return 'measure and one time period';
		if (needsPeriod) return 'time period';
		return needsExtract ? 'measure' : null;
	});

	const n = (v: number) => v.toLocaleString();

	// A measure's label from its extract option's description ("Label {{{...}}}")
	const measureLabel = (shortName: string) =>
		parseMeasure(shortName, dataset.extract_types.find((t) => t.short_name === shortName)?.description).label;
	const listLabels = (labels: string[]) =>
		labels.length <= 2 ? labels.join(' and ') : `${labels.slice(0, -1).join(', ')} and ${labels.at(-1)}`;
	const plural = (v: number, one: string, many = `${one}s`) => `${n(v)} ${v === 1 ? one : many}`;

	const where = $derived(
		`For each of the ${plural(features, 'feature')} ` +
			(boundaries === 1 ? 'in the boundary set you selected' : `across the ${n(boundaries)} boundary sets you selected`)
	);

	// Rasters: one column per statistic per time period (a categorical
	// statistic adds one per category instead).
	const raster = $derived.by(() => {
		const hasPeriods = dataset.temporal_name !== 'Temporally Invariant' && dataset.resources.length > 0;
		const periods = hasPeriods ? resources.length : 1;
		const labels = dataset.resources.filter((r) => resources.includes(r.name)).map((r) => r.label ?? r.name);
		const unit = periodUnit(labels);
		const categorical = extractTypes.some((t) => /categor/i.test(t));
		return {
			columns: extractTypes.length * periods,
			// "Average light intensity and Maximum light intensity across 3 years"
			text:
				listLabels(extractTypes.map((t) => measureLabel(t))) +
				(hasPeriods ? ` across ${plural(periods, unit[0], unit[1])}` : ''),
			categorical
		};
	});

	// Feature datasets: split fields multiply the columns; filter fields only
	// narrow the records.
	const feature = $derived.by(() => {
		const filters = Object.entries(dataset.filters ?? {});
		let columns = 1;
		const splits: string[] = [];
		let narrowed = 0;
		for (const [key, f] of filters) {
			const sel = filterSelections[key];
			if (f.aggregate === false) {
				const count = f.type === 'categorical' && sel?.type === 'categorical' ? sel.selected.length : 1;
				columns *= count;
				splits.push(`${f.display ?? key} (${n(count)})`);
			} else if (sel?.type === 'categorical' && f.type === 'categorical') {
				if (sel.selected.length < f.categories.length) narrowed++;
			} else if (sel?.type === 'range' && f.type === 'range') {
				if (sel.start > f.min || sel.end < f.max) narrowed++;
			}
		}
		const measure = dataset.outcomes?.[outcome] ?? null;
		return { columns, splits, narrowed, filterCount: filters.filter(([, f]) => f.aggregate !== false).length, measure };
	});

	// The sentence after the bold column count
	const featureTail = $derived(
		(feature.measure ? ` of ${feature.measure}` : '') +
			(feature.splits.length ? `, split by ${feature.splits.join(' and ')}` : '') +
			'.'
	);
</script>

<section aria-label="Output summary" class="mx-4 mt-4 rounded-md border bg-muted/40 px-4 py-3 text-sm">
	{#if empty}
		<p class="text-muted-foreground">No dataset selections currently made.</p>
	{:else}
	{#if isFeature}
		<p>
			{where}, your output will contain <strong>{plural(feature.columns, 'column')}</strong>{featureTail}
			{#if feature.filterCount > 0}
				{#if feature.narrowed > 0}
					The data will be filtered by the <strong>{plural(feature.narrowed, 'filter')}</strong> you narrowed.
				{:else}
					No filters narrow the data: every record is counted.
				{/if}
			{/if}
		</p>
	{:else}
		<p>
			{where}, your output will contain <strong>{plural(raster.columns, 'column')}</strong>, based on {raster.text}.
			{#if raster.categorical}
				A count by class adds one column for each class rather than one in total.
			{/if}
		</p>
	{/if}
	{/if}
	<!-- Where the options stand: added automatically for rasters, with Add to
	     Request (or Update) for feature datasets -->
	<p class="mt-2 flex items-start gap-1.5 text-xs text-muted-foreground" role="status">
		{#if !isFeature && missing}
			<CircleAlert class="size-4 shrink-0 text-warning-text" aria-hidden="true" />
			<span>Choose at least one {missing} to add this dataset to your request.</span>
		{:else if isFeature && saveState === 'incomplete' && featureMissingText}
			<CircleAlert class="size-4 shrink-0 text-warning-text" aria-hidden="true" />
			<span>Choose {featureMissingText} to add these options to your request.</span>
		{:else if saveState === 'saved'}
			<CircleCheck class="size-4 shrink-0 text-success-text" aria-hidden="true" />
			<span>
				<strong class="text-foreground">In your request.</strong>
				{isFeature ? 'Change the filters to add another version.' : 'Changes are saved automatically; Reset this dataset removes it.'}
			</span>
		{:else if saveState === 'unsaved'}
			<CircleAlert class="size-4 shrink-0 text-warning-text" aria-hidden="true" />
			<span>
				<strong class="text-foreground">Not added yet.</strong> These filters are saved, but they're only in
				your request once you add them.
			</span>
		{:else if saveState === 'editing'}
			<CircleAlert class="size-4 shrink-0 text-warning-text" aria-hidden="true" />
			<span>
				<strong class="text-foreground">Editing a version in your request.</strong> Update it, or add these
				filters as a new version.
			</span>
		{/if}
	</p>
</section>
