<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import { columnValues, detectBinary, getDatasetFieldTracks, getTemporalDatasets, colFieldTrack } from '$lib/viz';
	import { X, Plus, Download, ChevronDown } from '@lucide/svelte';
	import { zipSync } from 'fflate';
	import { exportPng } from '$lib/charts/exportPng';
	import type { FigureHandle } from '$lib/components/charts/PlotFigure.svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
	import ColumnSelect from './ColumnSelect.svelte';
	import OptionSelect from './OptionSelect.svelte';
	import { type ChartCard, type SingleColCard, type TimeSeriesCard, type ScatterCard, type CorrelationCard, CHART_TYPES } from './chartTypes';
	import Histogram from './charts/Histogram.svelte';
	import RankedBar from './charts/RankedBar.svelte';
	import BinaryBar from './charts/BinaryBar.svelte';
	import TimeSeries from './charts/TimeSeries.svelte';
	import Scatter from './charts/Scatter.svelte';
	import BoxPlot from './charts/BoxPlot.svelte';
	import CorrelationMatrix from './charts/CorrelationMatrix.svelte';

	interface Props {
		data: VizPayload;
	}
	let { data }: Props = $props();

	let chartCards = $state<ChartCard[]>([]);
	let showAddPicker = $state(false);
	let newCardCol = $state('');
	let newCardDatasetKey = $state('');
	let newCardFieldTrack = $state('');
	let newCardType = $state<ChartCard['type']>('histogram');
	let temporalDatasets = $derived(getTemporalDatasets(data));
	let newCardFieldTracks = $derived(getDatasetFieldTracks(data, newCardDatasetKey));
	// Feature id highlighted across the scatter and time-series charts
	let highlightedFeature = $state<string | null>(null);
	let exporting = $state(false);
	let activeFcs = $state(new Set<string>());

	let filteredData = $derived(
		activeFcs.size === data.fc_names.length
			? data
			: {
					...data,
					features: Object.fromEntries(
						Object.entries(data.features).filter(([, f]) => activeFcs.has(f.fc as string))
					)
				}
	);

	let columnsKey = $derived(data.columns.join('\x00'));
	let _lastKey = '';
	$effect(() => {
		const key = columnsKey;
		if (key === _lastKey) return;
		_lastKey = key;
		if (!data.columns.length) { chartCards = []; activeFcs = new Set(); return; }
		activeFcs = new Set(data.fc_names);

		const defaults: ChartCard[] = [];

		// Group temporal columns by dataset title (spans multiple yearly resource groups).
		// A valid time series requires at least one field track with ≥2 distinct temporal values.
		const temporalDatasets = getTemporalDatasets(data);
		const temporalGroup = Object.entries(temporalDatasets).find(([, cols]) => {
			const trackTimes = new Map<string, Set<string>>();
			for (const col of cols) {
				const track = colFieldTrack(col, data.col_temporal[col]);
				(trackTimes.get(track) ?? trackTimes.set(track, new Set()).get(track)!).add(data.col_temporal[col]);
			}
			return [...trackTimes.values()].some(times => times.size >= 2);
		});

		if (temporalGroup) {
			const [datasetTitle, cols] = temporalGroup;
			const tracks = getDatasetFieldTracks(data, datasetTitle);
			// Default to the field track with the most temporal values.
			const fieldTrack = tracks.length > 1
				? tracks.reduce((best, t) => {
					const tCount = cols.filter(c => colFieldTrack(c, data.col_temporal[c]) === t).length;
					const bCount = cols.filter(c => colFieldTrack(c, data.col_temporal[c]) === best).length;
					return tCount > bCount ? t : best;
				}, tracks[0])
				: undefined;
			defaults.push({
				id: crypto.randomUUID(), type: 'time_series',
				datasetKey: datasetTitle, columns: cols, aggregateMode: 'mean', fieldTrack
			} satisfies TimeSeriesCard);
		}

		const firstCol = data.columns[0];
		const firstType: SingleColCard['type'] = detectBinary(columnValues(data, firstCol)) ? 'binary_bar' : 'histogram';
		defaults.push({ id: crypto.randomUUID(), type: firstType, column: firstCol } satisfies SingleColCard);

		if (!temporalGroup) {
			defaults.push({ id: crypto.randomUUID(), type: 'top_bar', column: firstCol } satisfies SingleColCard);
		}

		chartCards = defaults;
		newCardCol = firstCol;
		newCardDatasetKey = Object.keys(getTemporalDatasets(data))[0] ?? Object.keys(data.col_groups)[0] ?? '';
		newCardType = 'histogram';
	});

	function removeCard(id: string) {
		chartCards = chartCards.filter((c) => c.id !== id);
	}

	function updateCard(id: string, patch: Partial<ChartCard>) {
		chartCards = chartCards.map((c) => (c.id === id ? { ...c, ...patch } as ChartCard : c));
	}

	function addCard() {
		if (newCardType === 'time_series') {
			const cols = temporalDatasets[newCardDatasetKey] ?? [];
			const tracks = getDatasetFieldTracks(data, newCardDatasetKey);
			const fieldTrack = tracks.length > 1 ? (newCardFieldTrack || tracks[0]) : undefined;
			chartCards = [...chartCards, {
				id: crypto.randomUUID(), type: 'time_series',
				datasetKey: newCardDatasetKey, columns: cols, aggregateMode: 'mean', fieldTrack
			} satisfies TimeSeriesCard];
		} else if (newCardType === 'scatter') {
			const firstCol = data.columns[0] ?? '';
			const secondCol = data.columns[1] ?? firstCol;
			chartCards = [...chartCards, {
				id: crypto.randomUUID(), type: 'scatter', xCol: firstCol, yCol: secondCol
			} satisfies ScatterCard];
		} else if (newCardType === 'correlation') {
			chartCards = [...chartCards, {
				id: crypto.randomUUID(), type: 'correlation', columns: data.columns.slice(0, 10)
			} satisfies CorrelationCard];
		} else if (newCardCol) {
			chartCards = [...chartCards, {
				id: crypto.randomUUID(), type: newCardType as SingleColCard['type'], column: newCardCol
			} satisfies SingleColCard];
		}
		showAddPicker = false;
	}

	// Each drawn chart's export handle, by card id
	let handles = $state<Record<string, FigureHandle | null>>({});

	function cardFilename(card: ChartCard): string {
		if (card.type === 'time_series') return `${card.datasetKey}_time_series.png`;
		if (card.type === 'scatter') return `${card.xCol}_vs_${card.yCol}_scatter.png`;
		if (card.type === 'correlation') return 'correlation_matrix.png';
		return `${card.column}_${card.type}.png`;
	}

	function download(blob: Blob, filename: string) {
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = filename;
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		URL.revokeObjectURL(url);
	}

	async function exportCard(card: ChartCard) {
		const handle = handles[card.id];
		if (!handle) return;
		const png = await exportPng(handle);
		if (png) download(png, cardFilename(card));
	}

	async function exportAll() {
		if (exporting) return;
		exporting = true;
		try {
			const files: { name: string; data: Uint8Array }[] = [];
			for (const card of chartCards) {
				const handle = handles[card.id];
				if (!handle) continue;
				const png = await exportPng(handle);
				if (png) files.push({ name: cardFilename(card), data: new Uint8Array(await png.arrayBuffer()) });
			}
			if (files.length === 0) return;

			// Deduplicate filenames
			const seen = new Map<string, number>();
			for (const f of files) {
				const count = seen.get(f.name) ?? 0;
				seen.set(f.name, count + 1);
				if (count > 0) f.name = f.name.replace('.png', `_${count}.png`);
			}

			const zip = zipSync(Object.fromEntries(files.map((f) => [f.name, f.data])));
			download(new Blob([zip.slice()], { type: "application/zip" }), "geoquery-charts.zip");
		} finally {
			exporting = false;
		}
	}

	const CHART_TYPE_OPTIONS = CHART_TYPES.map((ct) => ({ value: ct.value, label: ct.label }));
	const SINGLE_TYPE_OPTIONS = CHART_TYPES.filter((ct) => !ct.multi).map((ct) => ({
		value: ct.value as SingleColCard['type'],
		label: ct.label
	}));
	const AGGREGATE_OPTIONS: { value: TimeSeriesCard['aggregateMode']; label: string }[] = [
		{ value: 'all', label: 'All features' },
		{ value: 'mean', label: 'Mean only' },
		{ value: 'band', label: 'Mean + range' }
	];
	let datasetOptions = $derived(Object.keys(temporalDatasets).map((title) => ({ value: title, label: title })));
	const trackOptions = (tracks: string[]) => tracks.map((track) => ({ value: track, label: track }));

	function setFcActive(fc: string, active: boolean) {
		const next = new Set(activeFcs);
		if (active) next.add(fc);
		else next.delete(fc);
		activeFcs = next;
	}

</script>

<div class="h-full overflow-y-auto">
	<div class="space-y-4 p-4">
		{#if chartCards.length === 0 && data.columns.length === 0}
			<div class="flex h-48 items-center justify-center text-sm text-muted-foreground">
				No data available.
			</div>
		{:else}
			<!-- Toolbar: Add chart / boundary sets / Export All -->
			{#if data.columns.length > 0}
				{#if showAddPicker}
					<Card.Root class="max-w-sm gap-3 py-4">
						<Card.Content class="space-y-3 px-4">
							<p class="font-heading text-h4 font-bold">Add chart</p>
							<OptionSelect
								label="Chart type"
								value={newCardType}
								options={CHART_TYPE_OPTIONS}
								onchange={(v) => (newCardType = v)}
								class="w-full"
							/>
							{#if !CHART_TYPES.find((t) => t.value === newCardType)?.multi}
								<ColumnSelect {data} label="Column" value={newCardCol} onchange={(c) => (newCardCol = c)} class="w-full" />
							{:else if newCardType === 'time_series'}
								<OptionSelect
									label="Dataset"
									value={newCardDatasetKey}
									options={datasetOptions}
									onchange={(v) => (newCardDatasetKey = v)}
									class="w-full"
								/>
								{#if newCardFieldTracks.length > 1}
									<OptionSelect
										label="Field"
										value={newCardFieldTrack || newCardFieldTracks[0]}
										options={trackOptions(newCardFieldTracks)}
										onchange={(v) => (newCardFieldTrack = v)}
										class="w-full"
									/>
								{/if}
							{:else}
								<p class="text-sm text-muted-foreground">Choose the columns in the card after adding it.</p>
							{/if}
							<div class="flex items-center gap-2">
								<Button size="sm" onclick={addCard}>Add</Button>
								<Button size="sm" variant="outline" onclick={() => (showAddPicker = false)}>Cancel</Button>
							</div>
						</Card.Content>
					</Card.Root>
				{:else}
					<div class="flex flex-wrap items-center gap-2">
						<Button
							variant="ghost"
							size="sm"
							onclick={() => {
								showAddPicker = true;
								newCardCol = data.columns[0];
							}}
						>
							<Plus />
							Add chart
						</Button>
						{#if data.fc_names.length > 1}
							<DropdownMenu.Root>
								<DropdownMenu.Trigger>
									{#snippet child({ props })}
										<Button {...props} variant="ghost" size="sm" class="text-muted-foreground">
											{activeFcs.size === data.fc_names.length
												? `All ${data.fc_names.length} boundary sets`
												: `${activeFcs.size} of ${data.fc_names.length} boundary sets`}
											<ChevronDown />
										</Button>
									{/snippet}
								</DropdownMenu.Trigger>
								<DropdownMenu.Content align="start" class="w-64">
									<DropdownMenu.Label>Boundary sets</DropdownMenu.Label>
									{#each data.fc_names as fc (fc)}
										<DropdownMenu.CheckboxItem
											checked={activeFcs.has(fc)}
											onCheckedChange={(checked) => setFcActive(fc, checked)}
											closeOnSelect={false}
										>
											<span class="truncate">{fc}</span>
										</DropdownMenu.CheckboxItem>
									{/each}
									<DropdownMenu.Separator />
									<DropdownMenu.Item closeOnSelect={false} onclick={() => (activeFcs = new Set(data.fc_names))}>Select all</DropdownMenu.Item>
									<DropdownMenu.Item closeOnSelect={false} onclick={() => (activeFcs = new Set())}>Clear</DropdownMenu.Item>
								</DropdownMenu.Content>
							</DropdownMenu.Root>
						{/if}
						{#if chartCards.length > 0}
							<Button variant="ghost" size="sm" class="text-muted-foreground" onclick={exportAll} disabled={exporting}>
								<Download />
								{exporting ? 'Exporting…' : 'Export All'}
							</Button>
						{/if}
					</div>
				{/if}
			{/if}

			{#if activeFcs.size === 0 && data.fc_names.length > 0}
				<p class="py-10 text-center text-sm text-muted-foreground">
					No boundary sets selected. Choose at least one to draw the charts.
				</p>
			{:else}
				<div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
					{#each chartCards as card (card.id)}
						<Card.Root class="min-w-0 gap-0 overflow-visible py-0">
							<!-- Card header: what the chart shows -->
							<div class="flex flex-wrap items-center gap-2 rounded-t-xl bg-band px-3 py-2">
								{#if card.type === 'histogram' || card.type === 'top_bar' || card.type === 'bottom_bar' || card.type === 'binary_bar' || card.type === 'box_plot'}
									<ColumnSelect
										{data}
										label="Column"
										value={card.column}
										onchange={(column) => updateCard(card.id, { column } as Partial<SingleColCard>)}
										class="flex-1"
									/>
									<OptionSelect
										label="Chart type"
										value={card.type}
										options={SINGLE_TYPE_OPTIONS}
										onchange={(type) => updateCard(card.id, { type } as Partial<SingleColCard>)}
										class="shrink-0"
									/>
								{:else if card.type === 'time_series'}
									{@const tcTracks = getDatasetFieldTracks(data, card.datasetKey)}
									<OptionSelect
										label="Dataset"
										value={card.datasetKey}
										options={datasetOptions}
										onchange={(title) => {
											const dkTracks = getDatasetFieldTracks(data, title);
											updateCard(card.id, {
												datasetKey: title,
												columns: temporalDatasets[title] ?? [],
												fieldTrack: dkTracks.length > 1 ? dkTracks[0] : undefined
											} as Partial<TimeSeriesCard>);
										}}
										class="flex-1"
									/>
									{#if tcTracks.length > 1}
										<OptionSelect
											label="Field"
											value={card.fieldTrack ?? tcTracks[0]}
											options={trackOptions(tcTracks)}
											onchange={(fieldTrack) => updateCard(card.id, { fieldTrack } as Partial<TimeSeriesCard>)}
											class="flex-1"
										/>
									{/if}
									<OptionSelect
										label="Lines"
										value={card.aggregateMode}
										options={AGGREGATE_OPTIONS}
										onchange={(aggregateMode) => updateCard(card.id, { aggregateMode } as Partial<TimeSeriesCard>)}
										class="shrink-0"
									/>
								{:else if card.type === 'scatter'}
									<ColumnSelect
										{data}
										label="X axis column"
										value={card.xCol}
										onchange={(xCol) => updateCard(card.id, { xCol } as Partial<ScatterCard>)}
										class="flex-1"
									/>
									<span class="shrink-0 text-sm text-muted-foreground">vs</span>
									<ColumnSelect
										{data}
										label="Y axis column"
										value={card.yCol}
										onchange={(yCol) => updateCard(card.id, { yCol } as Partial<ScatterCard>)}
										class="flex-1"
									/>
								{:else if card.type === 'correlation'}
									<span class="flex-1 text-sm text-muted-foreground">{card.columns.length} columns selected</span>
								{/if}
								<div class="ml-auto flex shrink-0 items-center">
									<Button variant="ghost" size="icon-sm" onclick={() => exportCard(card)} disabled={!handles[card.id]} aria-label="Save chart as PNG">
										<Download />
									</Button>
									<Button variant="ghost" size="icon-sm" class="hover:text-destructive" onclick={() => removeCard(card.id)} aria-label="Remove chart">
										<X />
									</Button>
								</div>
							</div>

							<!-- Chart body -->
							<div class="p-4">
								{#if card.type === 'histogram'}
									<Histogram data={filteredData} {card} bind:handle={handles[card.id]} />
								{:else if card.type === 'top_bar' || card.type === 'bottom_bar'}
									<RankedBar data={filteredData} {card} bind:handle={handles[card.id]} />
								{:else if card.type === 'time_series'}
									<TimeSeries
										data={filteredData}
										{card}
										{highlightedFeature}
										onHighlight={(id) => (highlightedFeature = id)}
										bind:handle={handles[card.id]}
									/>
								{:else if card.type === 'scatter'}
									<Scatter
										data={filteredData}
										{card}
										{highlightedFeature}
										onHighlight={(id) => (highlightedFeature = id)}
										bind:handle={handles[card.id]}
									/>
								{:else if card.type === 'binary_bar'}
									<BinaryBar data={filteredData} {card} bind:handle={handles[card.id]} />
								{:else if card.type === 'box_plot'}
									<BoxPlot data={filteredData} {card} bind:handle={handles[card.id]} />
								{:else if card.type === 'correlation'}
									<CorrelationMatrix
										data={filteredData}
										{card}
										onCardUpdate={(patch) => updateCard(card.id, patch)}
										bind:handle={handles[card.id]}
									/>
								{/if}
							</div>
						</Card.Root>
					{/each}
				</div>
			{/if}
		{/if}
	</div>
</div>
