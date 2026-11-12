<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { Check, ChevronDown, Copy, ExternalLink } from '@lucide/svelte';
	import type { DatasetDetail } from '#lib/api.js';
	import {
		formatAddedUpdated,
		formatResolution,
		formatSpatialCoverage,
		formatTimeCoverage,
		linkParts
	} from './datasetMetadata.js';

	interface Props {
		dataset: DatasetDetail;
		/** From the dataset list: the detail endpoint does not carry the extent. */
		bbox?: [number, number, number, number] | null;
		/** Kept by the page so a panel stays open while switching datasets. */
		citeOpen?: boolean;
		moreOpen?: boolean;
	}

	let {
		dataset,
		bbox = null,
		citeOpen = $bindable(false),
		moreOpen = $bindable(false)
	}: Props = $props();

	let copied = $state(false);
	let copiedTimer: ReturnType<typeof setTimeout> | undefined;

	async function copyCitation() {
		if (!dataset.citation) return;
		try {
			await navigator.clipboard.writeText(dataset.citation);
			copied = true;
			clearTimeout(copiedTimer);
			copiedTimer = setTimeout(() => (copied = false), 2000);
		} catch {
			// Clipboard can be refused (insecure context, permissions); the
			// citation is on screen to select by hand.
		}
	}

	// Rows with no value are left out rather than shown as blanks.
	let rows = $derived(
		[
			['Resolution', formatResolution(dataset.resolution)],
			['Time coverage', formatTimeCoverage(dataset)],
			['Spatial coverage', formatSpatialCoverage(dataset.is_global, bbox)],
			['Processing notes', dataset.details?.trim() || null],
			['Version', dataset.version],
			['Type', dataset.processing_class === 'filter_and_agg' ? 'Feature' : 'Raster'],
			['Added / updated', formatAddedUpdated(dataset.date_added, dataset.date_updated)]
		].filter((r): r is [string, string] => !!r[1])
	);
</script>

<div class="mt-2 space-y-2 text-sm">
	<!-- Always visible: short, and needed to read the results. -->
	<p class="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground">
		{#if dataset.source_name}
			<span>
				Source:
				{#if dataset.source_url}
					<a
						href={dataset.source_url}
						target="_blank"
						rel="noopener noreferrer"
						class="inline-flex items-center gap-1 text-link hover:text-link-hover hover:underline"
					>
						{dataset.source_name}<ExternalLink class="h-3 w-3" />
					</a>
				{:else}
					{dataset.source_name}
				{/if}
			</span>
			<span aria-hidden="true">·</span>
		{/if}
		<!-- Always shown, even when unset: GeoQuery redistributes other
		     people's data, and "not recorded" is what tells the user they
		     still have to check the source. -->
		<span>
			License:
			{#if dataset.license}
				{#if dataset.license_url}
					<a
						href={dataset.license_url}
						target="_blank"
						rel="noopener noreferrer"
						class="inline-flex items-center gap-1 text-link hover:text-link-hover hover:underline"
					>
						{dataset.license}<ExternalLink class="h-3 w-3" />
					</a>
				{:else}
					{dataset.license}
				{/if}
			{:else}
				<span class="italic">not recorded — check the source</span>
			{/if}
		</span>
		{#if dataset.variable_description}
			<span aria-hidden="true">·</span>
			<span>Units: {dataset.variable_description}</span>
		{/if}
	</p>

	<div class="flex flex-wrap gap-2">
		{#if dataset.citation}
			<Button
				variant="outline"
				size="xs"
				aria-expanded={citeOpen}
				aria-controls="dataset-citation"
				onclick={() => (citeOpen = !citeOpen)}
			>
				How to cite
				<ChevronDown class="h-3.5 w-3.5 transition-transform {citeOpen ? 'rotate-180' : ''}" />
			</Button>
		{/if}
		<Button
			variant="outline"
			size="xs"
			aria-expanded={moreOpen}
			aria-controls="dataset-more-metadata"
			onclick={() => (moreOpen = !moreOpen)}
		>
			More metadata
			<ChevronDown class="h-3.5 w-3.5 transition-transform {moreOpen ? 'rotate-180' : ''}" />
		</Button>
	</div>

	{#if citeOpen && dataset.citation}
		<div id="dataset-citation" class="rounded-md border bg-card p-3">
			<div class="flex items-start gap-3">
				<p class="flex-1 leading-snug">
					{#each linkParts(dataset.citation) as part, i (i)}
						{#if part.href}
							<a
								href={part.href}
								target="_blank"
								rel="noopener noreferrer"
								class="break-all text-link hover:text-link-hover hover:underline">{part.text}</a
							>
						{:else}{part.text}{/if}
					{/each}
				</p>
				<Button variant="ghost" size="xs" onclick={copyCitation} aria-live="polite">
					{#if copied}
						<Check class="h-3.5 w-3.5" /> Copied
					{:else}
						<Copy class="h-3.5 w-3.5" /> Copy
					{/if}
				</Button>
			</div>
			<p class="mt-2 text-xs text-muted-foreground">
				Cite GeoQuery as well; both citations are in the documentation that comes with your
				request.
			</p>
		</div>
	{/if}

	{#if moreOpen}
		<dl
			id="dataset-more-metadata"
			class="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 rounded-md border bg-card p-3"
		>
			{#each rows as [label, value] (label)}
				<dt class="text-muted-foreground">{label}</dt>
				<dd>
					{#each linkParts(value) as part, i (i)}
						{#if part.href}
							<a
								href={part.href}
								target="_blank"
								rel="noopener noreferrer"
								class="break-all text-link hover:text-link-hover hover:underline">{part.text}</a
							>
						{:else}{part.text}{/if}
					{/each}
				</dd>
			{/each}
		</dl>
	{/if}
</div>
