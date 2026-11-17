<script lang="ts">
	import type { DatasetDetail } from '#lib/api.js';
	import { entryColumns } from '#lib/utils/outputColumns.js';

	// What one request entry extracts, as labelled rows: statistics and time
	// periods for rasters; measure, split fields and filters for feature
	// datasets. `detail` (the dataset's definition) supplies display names and
	// tells whether a filter was narrowed; without it, raw keys are shown.
	interface Props {
		extractTypes?: string[];
		resources?: string[];
		resourceLabels?: string[];
		kwargs?: Record<string, unknown> | null;
		detail?: DatasetDetail | null;
	}

	let { extractTypes = [], resources = [], resourceLabels = [], kwargs = null, detail = null }: Props = $props();

	const MAX_CHIPS = 12;
	const columns = $derived(entryColumns({ kwargs: kwargs ?? undefined, extractTypes, resources }));

	/** Values as chips: a run of consecutive years becomes one range chip. */
	function compact(values: string[]): string[] {
		if (values.length > 2 && values.every((v) => /^\d{4}$/.test(v))) {
			const years = values.map(Number).sort((a, b) => a - b);
			if (years.every((y, i) => i === 0 || y === years[i - 1] + 1)) return [`${years[0]}–${years.at(-1)}`];
		}
		return values;
	}

	type Filter = { label: string; chips: string[]; more: number; narrowed: boolean };
	const feature = $derived.by(() => {
		if (!kwargs) return null;
		const defs = detail?.filters ?? {};
		const splits: Filter[] = [];
		const filters: Filter[] = [];
		for (const [key, raw] of Object.entries(kwargs)) {
			if (key === 'outcome' || !raw || typeof raw !== 'object') continue;
			const v = raw as { type?: string; selected?: unknown[]; start?: number; end?: number; aggregate?: boolean };
			const def = defs[key];
			const label = def?.display ?? key;
			let values: string[] = [];
			let narrowed = true;
			if (v.type === 'categorical') {
				values = (v.selected ?? []).map(String);
				if (def?.type === 'categorical') narrowed = values.length < def.categories.length;
			} else if (v.type === 'range') {
				values = [`${v.start}–${v.end}`];
				if (def?.type === 'range') narrowed = (v.start ?? def.min) > def.min || (v.end ?? def.max) < def.max;
			}
			const chips = compact(values);
			const entry = { label, chips: chips.slice(0, MAX_CHIPS), more: Math.max(0, chips.length - MAX_CHIPS), narrowed };
			(v.aggregate === false ? splits : filters).push(entry);
		}
		const outcome = typeof kwargs.outcome === 'string' ? kwargs.outcome : null;
		return {
			measure: outcome ? (detail?.outcomes?.[outcome] ?? outcome) : null,
			splits,
			narrowed: filters.filter((f) => f.narrowed),
			unnarrowed: filters.filter((f) => !f.narrowed).map((f) => f.label)
		};
	});

	const periods = $derived(compact(resourceLabels.length === resources.length ? resourceLabels : resources));
</script>

{#snippet chips(list: string[], more = 0)}
	<span class="flex flex-wrap gap-1">
		{#each list as c (c)}
			<span class="rounded bg-muted px-1.5 py-0.5 text-xs text-foreground">{c}</span>
		{/each}
		{#if more > 0}<span class="px-1 text-xs text-muted-foreground">+{more} more</span>{/if}
	</span>
{/snippet}

<dl class="grid grid-cols-[max-content_1fr] items-baseline gap-x-4 gap-y-2 text-sm">
	<dt class="text-xs font-bold text-muted-foreground">Columns</dt>
	<dd class="tabular-nums">{columns.toLocaleString()} per feature</dd>

	{#if feature}
		{#if feature.measure}
			<dt class="text-xs font-bold text-muted-foreground">Measure</dt>
			<dd>{feature.measure}</dd>
		{/if}
		{#each feature.splits as s (s.label)}
			<dt class="text-xs font-bold text-muted-foreground">Split by {s.label}</dt>
			<dd>{@render chips(s.chips, s.more)}</dd>
		{/each}
		{#if feature.narrowed.length > 0 || feature.unnarrowed.length > 0}
			<dt class="col-span-2 mt-1 text-xs font-bold text-muted-foreground">Filters</dt>
			{#each feature.narrowed as f (f.label)}
				<dt class="pl-3 text-xs text-muted-foreground">{f.label}</dt>
				<dd>{@render chips(f.chips, f.more)}</dd>
			{/each}
			{#if feature.unnarrowed.length > 0}
				<dt class="pl-3 text-xs text-muted-foreground">Not narrowed</dt>
				<dd class="text-xs text-muted-foreground">{feature.unnarrowed.join(', ')}</dd>
			{/if}
		{/if}
	{:else}
		{#if extractTypes.length > 0}
			<dt class="text-xs font-bold text-muted-foreground">Statistics</dt>
			<dd>{@render chips(extractTypes)}</dd>
		{/if}
		{#if periods.length > 0}
			<dt class="text-xs font-bold text-muted-foreground">Time periods</dt>
			<dd>{@render chips(periods.slice(0, MAX_CHIPS), Math.max(0, periods.length - MAX_CHIPS))}</dd>
		{/if}
	{/if}
</dl>
