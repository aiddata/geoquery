<script lang="ts">
	import { onMount } from 'svelte';
	import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
	import { Button } from '$lib/components/ui/button';
	import BarChart from '$lib/components/stats/BarChart.svelte';
	import { fetchStats, type Stats } from '$lib/api';
	import { AlertCircle, RefreshCw } from '@lucide/svelte';

	let stats = $state<Stats | null>(null);
	let loading = $state(true);
	let error = $state('');

	// Nothing here polls. The payload is a snapshot the backend rebuilds on a
	// schedule (hourly by default); computing these counts per request meant
	// aggregating ~280M rows.
	async function load() {
		loading = true;
		error = '';
		try {
			stats = await fetchStats();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load statistics';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	type Period = 'day' | 'month' | 'year';
	type Field = 'submit_time' | 'complete_time';

	let period = $state<Period>('day');
	let field = $state<Field>('submit_time');
	let extPeriod = $state<Period>('day');

	const periods: Period[] = ['day', 'month', 'year'];

	let requestSeries = $derived(stats?.time_series?.[field]?.[period] ?? []);
	let extractSeries = $derived(stats?.extract_time_series?.[extPeriod] ?? []);

	const fmt = (n: number | undefined) => (n ?? 0).toLocaleString();
	const pct = (n: number | undefined, total: number | undefined) =>
		total && total > 0 ? (((n ?? 0) / total) * 100).toFixed(1) + '%' : '—';

	let cards = $derived([
		{ key: 'total', label: 'Total', value: stats?.total, sub: 'requests', accent: 'bg-muted-foreground' },
		{ key: 'completed', label: 'Completed', value: stats?.status_counts?.completed, accent: 'bg-success-text' },
		{ key: 'pending', label: 'Pending', value: stats?.status_counts?.pending, accent: 'bg-warning-text' },
		{ key: 'processing', label: 'Processing', value: stats?.status_counts?.processing, accent: 'bg-warning-text' },
		{ key: 'error', label: 'Error', value: stats?.status_counts?.error, accent: 'bg-danger-text' }
	]);

	let queueRows = $derived([
		{ label: 'Requests queued', value: stats?.status_counts?.pending, tone: 'text-warning-text' },
		{ label: 'Requests processing', value: stats?.status_counts?.processing, tone: 'text-warning-text' }
	]);

	let extractRows = $derived([
		{ label: 'Pending', value: stats?.extract_counts?.pending, tone: 'text-warning-text' },
		{ label: 'Claimed', value: stats?.extract_counts?.claimed, tone: 'text-warning-text' },
		{ label: 'Processing', value: stats?.extract_counts?.processing, tone: 'text-warning-text' },
		{ label: 'Error', value: stats?.extract_counts?.error, tone: 'text-danger-text' },
		{ label: 'Completed', value: stats?.extract_counts?.completed, tone: 'text-success-text' }
	]);
</script>

<svelte:head>
	<title>Statistics — GeoQuery</title>
</svelte:head>

<div class="mx-auto max-w-5xl px-4 py-8">
	<div class="mb-6 flex flex-wrap items-start justify-between gap-4">
		<div>
			<h1 class="text-h2">Statistics</h1>
			<p class="mt-1 text-sm text-muted-foreground">
				Usage summary across all submitted requests
			</p>
		</div>
		<div class="flex items-center gap-3">
			{#if stats}
				<span class="rounded-md border bg-muted px-3 py-1 text-xs text-muted-foreground">
					As of {stats.generated_at}
				</span>
			{/if}
			<Button variant="ghost" size="sm" onclick={load} disabled={loading}>
				<RefreshCw class={loading ? 'animate-spin' : ''} />
				<span class="sr-only sm:not-sr-only">Refresh</span>
			</Button>
		</div>
	</div>

	{#if error}
		<Card class="border-destructive/50">
			<CardContent class="flex items-center gap-3 py-6">
				<AlertCircle class="size-5 text-danger-text" aria-hidden="true" />
				<div>
					<div class="font-bold">Could not load statistics</div>
					<div class="text-sm text-muted-foreground">{error}</div>
				</div>
				<Button variant="outline" size="sm" class="ml-auto" onclick={load}>Try again</Button>
			</CardContent>
		</Card>
	{:else if loading && !stats}
		<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
			{#each Array(5) as _, i (i)}
				<Card><CardContent class="py-6"><div class="h-12 animate-pulse rounded bg-muted"></div></CardContent></Card>
			{/each}
		</div>
	{:else if stats}
		<!-- Request status cards -->
		<div class="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
			{#each cards as card (card.key)}
				<Card class="relative overflow-hidden">
					<div class="absolute inset-x-0 top-0 h-1 {card.accent}"></div>
					<CardContent class="pt-5">
						<div class="text-xs font-bold text-muted-foreground">
							{card.label}
						</div>
						<div class="mt-1 font-ui text-h2 font-bold tabular-nums">{fmt(card.value)}</div>
						<div class="mt-1 text-sm text-muted-foreground">
							{card.sub ?? pct(card.value, stats.total)}
						</div>
					</CardContent>
				</Card>
			{/each}
		</div>

		<!-- Queue status -->
		<Card class="mb-6">
			<CardHeader>
				<CardTitle>Queue Status</CardTitle>
			</CardHeader>
			<CardContent class="grid gap-6 sm:grid-cols-2">
				<div>
					<div class="mb-3 text-xs font-bold text-muted-foreground">
						Requests
					</div>
					<div class="flex flex-col gap-2">
						{#each queueRows as row (row.label)}
							<div class="flex items-center justify-between">
								<span class="text-sm text-muted-foreground">{row.label}</span>
								<span class="font-ui text-base font-bold tabular-nums {row.tone}">{fmt(row.value)}</span>
							</div>
						{/each}
					</div>
				</div>
				<div>
					<div class="mb-3 text-xs font-bold text-muted-foreground">
						Extract Tasks
					</div>
					<div class="flex flex-col gap-2">
						{#each extractRows as row (row.label)}
							<div class="flex items-center justify-between">
								<span class="text-sm text-muted-foreground">{row.label}</span>
								<span class="font-ui text-base font-bold tabular-nums {row.tone}">{fmt(row.value)}</span>
							</div>
						{/each}
					</div>
				</div>
			</CardContent>
		</Card>

		<!-- Requests over time -->
		<Card class="mb-4">
			<CardHeader class="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
				<CardTitle>Requests Over Time</CardTitle>
				<div class="flex items-center gap-2">
					<div class="flex overflow-hidden rounded-md border">
						{#each [['submit_time', 'Submitted'], ['complete_time', 'Completed']] as [value, text] (value)}
							<button
								class="min-h-8 px-3 py-1.5 font-ui text-xs font-bold transition-colors {field === value
									? 'bg-background text-foreground'
									: 'bg-muted text-muted-foreground hover:text-foreground'}"
								onclick={() => (field = value as Field)}
							>
								{text}
							</button>
						{/each}
					</div>
					<div class="flex overflow-hidden rounded-md border">
						{#each periods as p (p)}
							<button
								class="min-h-8 px-3 py-1.5 font-ui text-xs font-bold capitalize transition-colors {period === p
									? 'bg-background text-foreground'
									: 'bg-muted text-muted-foreground hover:text-foreground'}"
								onclick={() => (period = p)}
							>
								{p}
							</button>
						{/each}
					</div>
				</div>
			</CardHeader>
			<CardContent>
				<BarChart data={requestSeries} label="requests" color="var(--color-blue-600, #2563eb)" />
			</CardContent>
		</Card>

		<!-- Extract task completions -->
		<Card>
			<CardHeader class="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
				<CardTitle>Extract Task Completions</CardTitle>
				<div class="flex overflow-hidden rounded-md border">
					{#each periods as p (p)}
						<button
							class="min-h-8 px-3 py-1.5 font-ui text-xs font-bold capitalize transition-colors {extPeriod === p
								? 'bg-background text-foreground'
								: 'bg-muted text-muted-foreground hover:text-foreground'}"
							onclick={() => (extPeriod = p)}
						>
							{p}
						</button>
					{/each}
				</div>
			</CardHeader>
			<CardContent>
				<BarChart data={extractSeries} label="tasks" color="var(--color-green-600, #16a34a)" />
			</CardContent>
		</Card>
	{/if}
</div>
