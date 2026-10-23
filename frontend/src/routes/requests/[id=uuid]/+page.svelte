<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { fetchRequestDetail, type RequestDetail } from '$lib/api';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Collapsible from '$lib/components/ui/collapsible';
	import * as Alert from '$lib/components/ui/alert';
	import StatusBadge, { requestStatusMeaning } from '$lib/components/StatusBadge.svelte';
	import { ArrowLeft, Download, RefreshCw, ChevronRight, CircleAlert, Map } from '@lucide/svelte';
	import { formatKwargs } from '$lib/utils';

	const TERMINAL_STATUSES = new Set([1, -2]);

	let request = $state<RequestDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	async function load() {
		loading = true;
		error = null;
		try {
			request = await fetchRequestDetail(page.params.id);
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

	function formatResources(resources: string[], labels?: string[]): string {
		const display = labels ?? resources;
		const nums = display.map((r) => {
			const n = parseInt(r);
			return String(n) === r.trim() ? n : NaN;
		});
		if (nums.some((n) => isNaN(n))) return display.slice().sort().join(', ');
		const sorted = nums.slice().sort((a, b) => a - b);
		const groups: number[][] = [[sorted[0]]];
		for (let i = 1; i < sorted.length; i++) {
			const last = groups[groups.length - 1];
			if (sorted[i] === last[last.length - 1] + 1) last.push(sorted[i]);
			else groups.push([sorted[i]]);
		}
		return groups
			.map((g) => (g.length > 2 ? `${g[0]}-${g[g.length - 1]}` : g.join(', ')))
			.join(', ');
	}

	let featureCount = $derived(request?.data?.feature_ids?.length ?? 0);

	function formatOperation(op: { type: string; params: Record<string, unknown> }): string {
		if (op.type === 'buffer') return `Buffer — ${op.params.distance ?? ''} ${op.params.units ?? 'km'}`;
		if (op.type === 'simplify') return `Simplify — tolerance ${op.params.tolerance ?? ''}°`;
		if (op.type === 'union') return 'Union features';
		return op.type;
	}
</script>

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
		<p class="text-danger-text">{error}</p>
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
							<div class="flex items-center gap-2">
								<a href={`/api/visualize/request/${request.id}/export/?format=colab`} target="_blank" rel="noopener noreferrer">
									<img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab" />
								</a>
								<a href={`/api/visualize/request/${request.id}/export/?format=marimo`} target="_blank" rel="noopener noreferrer">
									<img src="https://marimo.io/molab-shield.svg" alt="Open in molab" />
								</a>
							</div>
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
							<p class="mt-0.5 text-xs text-muted-foreground">
								{featureCount} feature{featureCount === 1 ? '' : 's'} total
							</p>
						{/if}
						{#if request.data.boundary_operations?.length > 0}
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
			{#if request.data?.datasets?.length > 0}
				<div class="space-y-3">
					{#each request.data.datasets as item}
						<Card.Root>
							<Card.Header class="pb-3">
								<Collapsible.Root class="min-w-0">
									<div class="min-w-0 flex items-center gap-3">
										<Collapsible.Trigger>
											{#snippet child({ props })}
												<Button {...props} variant="ghost" size="icon-sm" class="text-muted-foreground" aria-label="Show details for {item.dataset_name}">
													<ChevronRight class="transition-transform [[data-state=open]_&]:rotate-90" />
												</Button>
											{/snippet}
										</Collapsible.Trigger>
										<p class="min-w-0 flex-1 truncate text-sm font-bold">{item.dataset_name}</p>
									</div>

									<Collapsible.Content class="mt-3 space-y-1 pl-7 text-sm text-muted-foreground">
										{#if item.dataset_type}
											<p><span class="font-bold">Type:</span> {item.dataset_type}</p>
										{/if}
										{#if item.extract_types && item.extract_types.length > 0}
											<p>
												<span class="font-bold">Extract types:</span>
												{item.extract_types.join(', ')}
											</p>
										{/if}
										{#if item.resources && item.resources.length > 0}
											<p>
												<span class="font-bold">Time periods:</span>
												{formatResources(item.resources, item.resource_labels)}
											</p>
										{/if}
										{#if item.kwargs}
											<p>
												<span class="font-bold">Filters:</span>
												{formatKwargs(item.kwargs)}
											</p>
										{/if}
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
