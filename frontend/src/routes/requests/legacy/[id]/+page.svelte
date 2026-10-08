<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { Button } from '$lib/components/ui/button';
	import { ArrowLeft, Archive, Download } from '@lucide/svelte';
	import { fetchLegacyRequestDetail, type LegacyRequestDetail } from '$lib/api';

	const id = $derived(page.params.id ?? '');

	let request = $state<LegacyRequestDetail | null>(null);
	let loading = $state(true);
	let error = $state('');

	$effect(() => {
		if (!id) return;
		loading = true;
		error = '';
		fetchLegacyRequestDetail(id)
			.then((r) => {
				request = r;
			})
			.catch(() => {
				error = 'This archived request could not be found.';
			})
			.finally(() => {
				loading = false;
			});
	});

	/* The old system wrote its stage times out of order: complete_time precedes
	   submit_time in about a fifth of the archive. Day-granularity display hides
	   almost all of it, but a few dozen rows straddle a UTC date boundary and
	   would render a completion before its own submission. Show nothing rather
	   than a contradiction. */
	const completedIsSound = $derived(
		!!request &&
			new Date(request.complete_time).getTime() >=
				new Date(request.submit_time).getTime()
	);

	const fmt = (iso: string | null) =>
		iso
			? new Date(iso).toLocaleDateString(undefined, {
					year: 'numeric',
					month: 'long',
					day: 'numeric'
				})
			: '—';
</script>

<div class="container mx-auto max-w-2xl px-4 py-8">
	<div class="mb-6">
		<Button variant="ghost" onclick={() => goto('/requests')}>
			<ArrowLeft class="mr-1 h-4 w-4" />
			Back to Requests
		</Button>
	</div>

	<div class="rounded-lg border bg-card p-6 shadow-sm">
		{#if loading}
			<p class="text-center text-muted-foreground">Loading…</p>
		{:else if error || !request}
			<h1 class="mb-2 text-2xl font-semibold">Not Found</h1>
			<p class="text-muted-foreground">{error}</p>
		{:else}
			<div class="mb-4 flex items-start justify-between gap-3">
				<h1 class="text-2xl font-semibold">
					{request.name || 'Unnamed Request'}
				</h1>
				<span
					class="flex shrink-0 items-center gap-1 rounded-full bg-muted px-2 py-1 text-xs font-medium text-muted-foreground"
				>
					<Archive class="h-3 w-3" />
					archived
				</span>
			</div>

			<p class="mb-6 text-sm text-muted-foreground">
				This request was submitted to a previous version of GeoQuery. Its results remain
				available to download, but it cannot be re-run or visualized, and its datasets are not
				linked to the current catalog.
			</p>

			<dl class="space-y-3 text-sm">
				<div class="flex justify-between gap-4 border-b pb-2">
					<dt class="text-muted-foreground">Submitted</dt>
					<dd class="text-right">{fmt(request.submit_time)}</dd>
				</div>
				<div class="flex justify-between gap-4 border-b pb-2">
					<dt class="text-muted-foreground">Completed</dt>
					<dd class="text-right">{completedIsSound ? fmt(request.complete_time) : "—"}</dd>
				</div>
				<div class="flex justify-between gap-4 border-b pb-2">
					<dt class="text-muted-foreground">Boundary</dt>
					<dd class="text-right">{request.boundary_title}</dd>
				</div>
			</dl>

			<h2 class="mb-2 mt-6 text-sm font-medium">
				Datasets ({request.dataset_count})
			</h2>
			{#if request.dataset_titles.length > 0}
				<ul class="space-y-1 text-sm text-muted-foreground">
					{#each request.dataset_titles as title}
						<li class="rounded border bg-muted/20 px-3 py-1.5">{title}</li>
					{/each}
				</ul>
			{:else}
				<p class="text-sm text-muted-foreground">
					No dataset names were recorded for this request.
				</p>
			{/if}

			{#if request.download_url}
				<div class="mt-6">
					<Button href={request.download_url}>
						<Download class="mr-1 h-4 w-4" />
						Download Results
					</Button>
				</div>
			{/if}
		{/if}
	</div>
</div>
