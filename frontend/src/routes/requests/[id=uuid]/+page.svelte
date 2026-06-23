<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { fetchRequestDetail, type RequestDetail } from '$lib/api';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Collapsible from '$lib/components/ui/collapsible';
	import { ArrowLeft, Download, RefreshCw, ChevronRight, Map } from '@lucide/svelte';
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

	function statusClass(label: string) {
		if (label === 'completed') return 'bg-green-100 text-green-800';
		if (label === 'processing' || label === 'preparing') return 'bg-yellow-100 text-yellow-800';
		if (label === 'error') return 'bg-red-100 text-red-800';
		return 'bg-gray-100 text-gray-800';
	}

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
			<ArrowLeft class="mr-1 h-4 w-4" />
			Back
		</Button>
	</div>

	{#if loading && !request}
		<p class="text-muted-foreground">Loading…</p>
	{:else if error}
		<p class="text-destructive">{error}</p>
	{:else if request}
		<div class="space-y-4">

			<!-- Header -->
			<div class="rounded-lg border bg-card p-6 shadow-sm">
				<div class="flex items-start justify-between gap-4">
					<div>
						<h1 class="text-xl font-semibold">{request.name || 'Unnamed Request'}</h1>
						<p class="mt-0.5 text-xs text-muted-foreground">ID: {request.id}</p>
					</div>
					<div class="flex items-center gap-2">
						<span class="rounded-full px-3 py-1 text-xs font-medium {statusClass(request.status_label)}">
							{request.status_label}
						</span>
						{#if !TERMINAL_STATUSES.has(request.status)}
							<button onclick={load} class="text-muted-foreground hover:text-foreground" title="Refresh">
								<RefreshCw class="h-4 w-4" />
							</button>
						{/if}
					</div>
				</div>

				<div class="mt-4 grid grid-cols-2 gap-3 text-sm">
					<div>
						<p class="text-xs font-medium text-muted-foreground">Submitted</p>
						<p>{fmt(request.submit_time)}</p>
					</div>
					<div>
						<p class="text-xs font-medium text-muted-foreground">Completed</p>
						<p>{fmt(request.complete_time)}</p>
					</div>
				</div>

				{#if request.download_url}
					<div class="mt-4 rounded-md border border-green-200 bg-green-50 p-4">
						<p class="mb-3 text-sm font-medium text-green-800">Your data is ready to download.</p>
						<div class="flex flex-col gap-3">
							<div class="flex flex-wrap gap-2">
								<Button href={request.download_url} target="_blank" rel="noopener noreferrer">
									<Download class="mr-2 h-4 w-4" />
									Download Results
								</Button>
								{#if request.visualization_url}
									<Button variant="outline" href={request.visualization_url}>
										<Map class="mr-2 h-4 w-4" />
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
						</div>
					</div>
				{:else if request.status_label === 'completed'}
					<p class="mt-4 text-sm text-muted-foreground">Your data is ready. Check your email for a download link.</p>
				{:else if request.status !== -2}
					<p class="mt-4 text-sm text-muted-foreground">Your request is being processed. You'll receive an email when it's ready.</p>
				{/if}

				{#if request.status === -2}
					<p class="mt-4 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
						This request encountered an error during processing. Please contact support if this persists.
					</p>
				{/if}
			</div>

			<!-- Geographic selection -->
			{#if request.data?.selection_label}
				<Card.Root class="bg-muted/40">
					<Card.Header class="pb-3">
						<p class="text-xs font-medium uppercase tracking-wide text-muted-foreground">
							{request.data.is_custom_boundary ? 'Custom Boundary' : 'Geographic Selection'}
						</p>
						<p class="mt-1 font-semibold">{request.data.selection_label}</p>
						{#if request.data.selection_detail}
							<p class="text-sm text-muted-foreground">{request.data.selection_detail}</p>
						{/if}
						{#if featureCount > 0}
							<p class="mt-0.5 text-xs text-muted-foreground">
								{featureCount} feature{featureCount === 1 ? '' : 's'} total
							</p>
						{/if}
						{#if request.data.boundary_operations?.length > 0}
							<div class="mt-2 border-t pt-2">
								<p class="text-xs font-medium text-muted-foreground">
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
								<Collapsible.Root>
									<div class="flex items-center gap-3">
										<Collapsible.Trigger class="flex items-center text-muted-foreground hover:text-foreground">
											<ChevronRight class="h-4 w-4 transition-transform [[data-state=open]_&]:rotate-90" />
										</Collapsible.Trigger>
										<p class="flex-1 text-sm font-medium">{item.dataset_name}</p>
									</div>

									<Collapsible.Content class="mt-3 space-y-1 pl-7 text-sm text-muted-foreground">
										{#if item.dataset_type}
											<p><span class="font-medium">Type:</span> {item.dataset_type}</p>
										{/if}
										{#if item.extract_types && item.extract_types.length > 0}
											<p>
												<span class="font-medium">Extract types:</span>
												{item.extract_types.join(', ')}
											</p>
										{/if}
										{#if item.resources && item.resources.length > 0}
											<p>
												<span class="font-medium">Time periods:</span>
												{formatResources(item.resources, item.resource_labels)}
											</p>
										{/if}
										{#if item.kwargs}
											<p>
												<span class="font-medium">Filters:</span>
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
