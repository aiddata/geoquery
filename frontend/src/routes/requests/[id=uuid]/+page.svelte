<script lang="ts">
	import Seo from '#lib/components/layout/Seo.svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { fetchDatasetDetail, fetchRequestDetail, fetchRequestRecipe, type DatasetDetail, type RequestDetail } from '#lib/api.js';
	import { loadRequestTemplate, requestInProgress } from '#lib/loadRecipe.js';
	import ShareLinkButton from '#lib/components/ShareLinkButton.svelte';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';
	import DatasetEntryDetails from '#lib/components/datasets/DatasetEntryDetails.svelte';
	import { entryColumns } from '#lib/utils/outputColumns.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Card from '#lib/components/ui/card/index.js';
	import * as Collapsible from '#lib/components/ui/collapsible/index.js';
	import * as Alert from '#lib/components/ui/alert/index.js';
	import StatusBadge, { requestStatusMeaning } from '#lib/components/StatusBadge.svelte';
	import { ArrowLeft, Download, RefreshCw, ChevronRight, CircleAlert, CopyPlus, Map } from '@lucide/svelte';
	import { features } from '#lib/stores/features.js';

	const TERMINAL_STATUSES = new Set([1, -2]);

	let request = $state<RequestDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	async function load() {
		loading = true;
		error = null;
		try {
			// The [id=uuid] route only matches with an id, so it is always set.
			request = await fetchRequestDetail(page.params.id as string);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load request.';
		} finally {
			loading = false;
		}
	}

	$effect(() => { load(); });

	$effect(() => {
		if (!request || TERMINAL_STATUSES.has(request.status)) return;
		const interval = setInterval(load, 15000);
		return () => clearInterval(interval);
	});

	function fmt(dateStr: string | null) {
		if (!dateStr) return '—';
		return new Date(dateStr).toLocaleString();
	}

	let featureCount = $derived(request?.data?.feature_ids?.length ?? 0);

	const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;
	// Requests don't store how many boundary sets they used; the saved summary
	// says "N boundary sets" (or, before Nov 2026, "N boundary collections")
	// when there were several.
	let boundarySets = $derived.by(() => {
		const m = request?.data?.selection_detail?.match(/(\d+) boundary (?:sets?|collections?)/);
		return m ? Number(m[1]) : 1;
	});
	let boundarySummary = $derived(
		request?.data?.is_custom_boundary
			? `${plural(featureCount, 'feature')} in a custom boundary`
			: `${plural(featureCount, 'feature')} across ${boundarySets === 1 ? '1 boundary set' : `${boundarySets} boundary sets`}`
	);

	// Each stored dataset as the column helper and details component read it
	const entries = $derived(
		(request?.data?.datasets ?? []).map((d) => ({
			...d,
			source: { kwargs: d.kwargs ?? undefined, extractTypes: d.extract_types ?? [], resources: d.resources ?? [] }
		}))
	);
	let totalColumns = $derived(entries.reduce((n, e) => n + entryColumns(e.source), 0));

	// Dataset definitions, for titles, display names and filter details
	let details = $state<Record<string, DatasetDetail>>({});
	$effect(() => {
		for (const name of new Set(entries.map((e) => e.dataset_name))) {
			if (details[name]) continue;
			fetchDatasetDetail(name)
				.then((d) => (details = { ...details, [name]: d }))
				.catch(() => {});
		}
	});

	// "Use as template" (GEO-126): start a new request with this one's
	// boundaries and datasets, replacing the one being built after a confirm.
	let confirmReplace = $state(false);
	let templateLoading = $state(false);
	let templateError = $state<string | null>(null);

	function startTemplate() {
		templateError = null;
		if (requestInProgress()) confirmReplace = true;
		else useTemplate();
	}

	async function useTemplate() {
		if (!request) return;
		confirmReplace = false;
		templateLoading = true;
		try {
			const result = await fetchRequestRecipe(request.id);
			await goto(loadRequestTemplate(result, request.name || 'Unnamed Request'));
		} catch (e) {
			templateError = e instanceof Error ? e.message : "This request couldn't be loaded as a template.";
		} finally {
			templateLoading = false;
		}
	}

	function formatOperation(op: { type: string; params: Record<string, unknown> }): string {
		if (op.type === 'buffer') return `Buffer — ${op.params.distance ?? ''} ${op.params.units ?? 'km'}`;
		if (op.type === 'simplify') return `Simplify — tolerance ${op.params.tolerance ?? ''}°`;
		if (op.type === 'union') return 'Union features';
		return op.type;
	}
</script>

<Seo title="Request" noindex />

<div class="container mx-auto max-w-2xl px-4 py-8">
	<div class="mb-6">
		<Button variant="ghost" onclick={() => goto('/requests')}>
			<ArrowLeft />
			Back
		</Button>
	</div>

	{#if loading && !request}
		<p class="text-muted-foreground">Loading…</p>
	{:else if error}
		<h1 class="mb-2 text-h3">Request unavailable</h1>
		<p class="text-danger-text" role="alert">{error}</p>
	{:else if request}
		<div class="space-y-4">

			<!-- Header -->
			<div class="card-surface p-6">
				<div class="flex items-start justify-between gap-4">
					<div>
						<h1 class="text-h3">{request.name || 'Unnamed Request'}</h1>
						<p class="mt-0.5 text-xs text-muted-foreground">ID: <span class="font-ui font-bold">{request.id}</span></p>
					</div>
					<div class="flex items-center gap-2">
						<StatusBadge meaning={requestStatusMeaning(request.status)}>
							{request.status_label}
						</StatusBadge>
						{#if !TERMINAL_STATUSES.has(request.status)}
							<Button variant="ghost" size="icon-sm" onclick={load} class="text-muted-foreground" aria-label="Refresh status">
								<RefreshCw />
							</Button>
						{/if}
					</div>
				</div>

				<div class="mt-4 grid grid-cols-2 gap-3 text-sm">
					<div>
						<p class="text-xs font-bold text-muted-foreground">Submitted</p>
						<p>{fmt(request.submit_time)}</p>
					</div>
					<div>
						<p class="text-xs font-bold text-muted-foreground">Completed</p>
						<p>{fmt(request.complete_time)}</p>
					</div>
				</div>

				<div class="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2">
					{#if request.data?.is_custom_boundary}
						<!-- Unavailable, but still focusable (aria-disabled) so its tooltip
						     says why -->
						<Tooltip.Root>
							<Tooltip.Trigger>
								{#snippet child({ props })}
									<Button {...props} variant="outline" size="sm" aria-disabled="true" class="cursor-not-allowed opacity-50">
										<CopyPlus />
										Use as template
									</Button>
								{/snippet}
							</Tooltip.Trigger>
							<Tooltip.Content>Requests with a custom upload can't be used as a template.</Tooltip.Content>
						</Tooltip.Root>
					{:else}
						<Button variant="outline" size="sm" onclick={startTemplate} disabled={templateLoading}>
							<CopyPlus />
							{templateLoading ? 'Loading…' : 'Use as template'}
						</Button>
						<p class="text-xs text-muted-foreground">Start a new request with these boundaries and datasets.</p>
					{/if}
				</div>
				<ShareLinkButton
					class="mt-3"
					getRecipe={async () => (await fetchRequestRecipe(request!.id)).recipe}
					unavailable={request.data?.is_custom_boundary ? "Requests with a custom upload can't be shared." : null}
				/>
				{#if templateError}
					<p class="mt-2 text-sm text-danger-text" role="alert">{templateError}</p>
				{/if}

				{#if request.download_url}
					<Alert.Root variant="success" role="status" class="mt-4 p-4">
						<Alert.Title class="mb-2">Your data is ready to download.</Alert.Title>
						<Alert.Description class="flex flex-col gap-3">
							<div class="flex flex-wrap gap-2">
								<Button href={request.download_url} target="_blank" rel="noopener noreferrer">
									<Download />
									Download Results
								</Button>
								{#if request.visualization_url}
									<Button variant="outline" href={request.visualization_url}>
										<Map />
										Visualize Data
									</Button>
								{/if}
								{#if request.documentation_url}
									<Button variant="outline" href={request.documentation_url} target="_blank" rel="noopener noreferrer">
										Read Documentation
									</Button>
								{/if}
							</div>
							{#if $features.has('notebook_export')}
								<div class="flex items-center gap-2">
									<a href={`/api/visualize/request/${request.id}/export/?format=colab`} target="_blank" rel="noopener noreferrer">
										<img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab" />
									</a>
									<a href={`/api/visualize/request/${request.id}/export/?format=marimo`} target="_blank" rel="noopener noreferrer">
										<img src="https://marimo.io/molab-shield.svg" alt="Open in molab" />
									</a>
								</div>
							{/if}
						</Alert.Description>
					</Alert.Root>
				{:else if request.status_label === 'completed'}
					<p class="mt-4 text-sm text-muted-foreground">Your data is ready. Check your email for a download link.</p>
				{:else if request.status !== -2}
					<p class="mt-4 text-sm text-muted-foreground">Your request is being processed. You'll receive an email when it's ready.</p>
				{/if}

				{#if request.status === -2}
					<Alert.Root variant="destructive" class="mt-4">
						<CircleAlert />
						<Alert.Description>
							This request encountered an error during processing. Please contact support if this persists.
						</Alert.Description>
					</Alert.Root>
				{/if}
			</div>

			<!-- Geographic selection -->
			{#if request.data?.selection_label}
				<Card.Root>
					<Card.Header class="pb-3">
						<p class="text-xs font-bold text-muted-foreground">
							{request.data.is_custom_boundary ? 'Custom Boundary' : 'Geographic Selection'}
						</p>
						<p class="mt-1 truncate font-bold" title={request.data.selection_label}>{request.data.selection_label}</p>
						{#if request.data.selection_detail}
							<p class="truncate text-sm text-muted-foreground">{request.data.selection_detail}</p>
						{/if}
						{#if featureCount > 0}
							<p class="mt-0.5 text-xs text-muted-foreground">{boundarySummary}</p>
						{/if}
						{#if request.data.boundary_operations?.length}
							<div class="mt-2 border-t pt-2">
								<p class="text-xs font-bold text-muted-foreground">
									Operations applied ({request.data.boundary_operations.length})
								</p>
								<ol class="mt-1 space-y-0.5 pl-4 text-xs text-muted-foreground list-decimal">
									{#each request.data.boundary_operations as op}
										<li>{formatOperation(op)}</li>
									{/each}
								</ol>
							</div>
						{/if}
					</Card.Header>
				</Card.Root>
			{/if}

			<!-- Dataset items -->
			{#if entries.length > 0}
				<div class="space-y-3">
					<p class="text-xs text-muted-foreground">
						{plural(totalColumns, 'column')} across {plural(entries.length, 'dataset selection')}
					</p>
					{#each entries as item, i (i)}
						{@const title = details[item.dataset_name]?.title ?? item.dataset_name}
						<Card.Root>
							<Card.Header class="pb-3">
								<Collapsible.Root class="min-w-0">
									<div class="min-w-0 flex items-center gap-3">
										<Collapsible.Trigger>
											{#snippet child({ props })}
												<Button {...props} variant="ghost" size="icon-sm" class="text-muted-foreground" aria-label="Show details for {item.name ?? title}">
													<ChevronRight class="transition-transform [[data-state=open]_&]:rotate-90" />
												</Button>
											{/snippet}
										</Collapsible.Trigger>
										<div class="min-w-0 flex-1">
											<p class="truncate text-sm font-bold">{item.name ?? title}</p>
											{#if item.name}<p class="truncate text-xs text-muted-foreground">{title}</p>{/if}
										</div>
										<span class="shrink-0 text-xs tabular-nums text-muted-foreground">
											{plural(entryColumns(item.source), 'column')}
										</span>
									</div>

									<Collapsible.Content class="mt-3 pl-7">
										<DatasetEntryDetails
											extractTypes={item.extract_types}
											resources={item.resources}
											resourceLabels={item.resource_labels}
											kwargs={item.kwargs}
											detail={details[item.dataset_name]}
										/>
									</Collapsible.Content>
								</Collapsible.Root>
							</Card.Header>
						</Card.Root>
					{/each}
				</div>
			{/if}

		</div>
	{/if}
</div>

<Dialog.Root bind:open={confirmReplace}>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>Replace your current request?</Dialog.Title>
			<Dialog.Description>
				The boundaries and datasets you've chosen so far will be replaced with this request's.
			</Dialog.Description>
		</Dialog.Header>
		<Dialog.Footer>
			<Button variant="outline" onclick={() => (confirmReplace = false)}>Keep current request</Button>
			<Button onclick={useTemplate}>Replace</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
