<script lang="ts">
	import Seo from '#lib/components/layout/Seo.svelte';
	import { onMount } from 'svelte';
	import { Card, CardContent, CardHeader, CardTitle } from '#lib/components/ui/card/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import BarChart from '#lib/components/stats/BarChart.svelte';
	import {
		fetchStats,
		fetchServiceStatus,
		type Stats,
		type StatsPoint,
		type ServiceStatus
	} from '#lib/api.js';
	import { AlertCircle, RefreshCw } from '@lucide/svelte';

	let stats = $state<Stats | null>(null);
	let loading = $state(true);
	let error = $state('');

	// The snapshot is rebuilt on a schedule (hourly by default): computing these
	// counts per request meant aggregating ~280M rows, so nothing here polls it.
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

	// The status line is live and cheap (one query on the small requests
	// table), so it refreshes every minute. Failing to reach it at all is
	// what "offline" means.
	let status = $state<ServiceStatus | null>(null);
	let statusFailed = $state(false);
	async function loadStatus() {
		try {
			status = await fetchServiceStatus();
			statusFailed = false;
		} catch {
			statusFailed = true;
		}
	}

	onMount(() => {
		load();
		loadStatus();
		const timer = setInterval(loadStatus, 60_000);
		return () => clearInterval(timer);
	});

	function refresh() {
		load();
		loadStatus();
	}

	type Period = 'day' | 'month' | 'year';
	type Field = 'submit_time' | 'complete_time';
	const periods: Period[] = ['day', 'month', 'year'];

	let period = $state<Period>('day');
	let field = $state<Field>('submit_time');
	let extPeriod = $state<Period>('day');

	let requestSeries = $derived(stats?.time_series?.[field]?.[period] ?? []);
	let extractSeries = $derived(stats?.extract_time_series?.[extPeriod] ?? []);

	const fmt = (n: number | undefined | null) => (n ?? 0).toLocaleString();

	function duration(seconds: number | null | undefined): string {
		if (seconds == null) return '—';
		const minutes = seconds / 60;
		if (minutes < 1) return 'under 1 min';
		if (minutes < 90) return `${Math.round(minutes)} min`;
		const hours = minutes / 60;
		if (hours < 48) return `${hours.toFixed(1)} h`;
		return `${(hours / 24).toFixed(1)} days`;
	}

	/** Sum a daily series over the last `days` days, counting today as one. */
	function lastDays(series: StatsPoint[] | undefined, days: number): number {
		if (!series?.length) return 0;
		const since = new Date();
		since.setUTCDate(since.getUTCDate() - (days - 1));
		const cutoff = since.toISOString().slice(0, 10);
		return series.filter((p) => p.date >= cutoff).reduce((n, p) => n + p.count, 0);
	}

	type Segment = { label: string; value: number; color: string };

	let requestSegments = $derived<Segment[]>([
		{ label: 'Completed', value: stats?.status_counts?.completed ?? 0, color: 'var(--chart-1)' },
		{ label: 'Queued', value: stats?.status_counts?.pending ?? 0, color: 'var(--chart-2)' },
		{ label: 'Processing', value: stats?.status_counts?.processing ?? 0, color: 'var(--chart-3)' },
		{ label: 'Error', value: stats?.status_counts?.error ?? 0, color: 'var(--danger)' }
	]);

	let taskSegments = $derived<Segment[]>([
		{ label: 'Completed', value: stats?.extract_counts?.completed ?? 0, color: 'var(--chart-1)' },
		{ label: 'Pending', value: stats?.extract_counts?.pending ?? 0, color: 'var(--chart-2)' },
		{ label: 'Claimed', value: stats?.extract_counts?.claimed ?? 0, color: 'var(--chart-4)' },
		{ label: 'Processing', value: stats?.extract_counts?.processing ?? 0, color: 'var(--chart-3)' },
		{ label: 'Error', value: stats?.extract_counts?.error ?? 0, color: 'var(--danger)' }
	]);

	let headline = $derived([
		{
			label: 'Requests completed',
			value: stats?.status_counts?.completed,
			note: stats?.legacy_request_count
				? `plus ${fmt(stats.legacy_request_count)} from earlier versions`
				: null
		},
		{ label: 'Results extracted', value: stats?.extract_counts?.completed, note: 'one per area, dataset and period' },
		{ label: 'Datasets available', value: stats?.datasets_available, note: null },
		{ label: 'Boundary sets available', value: stats?.boundary_sets_available, note: null }
	]);

	const STATUS_TEXT = {
		healthy: { label: 'Healthy', color: 'var(--success-text)', detail: 'Requests are being processed normally.' },
		backlogged: { label: 'Backlogged', color: 'var(--warning-text)', detail: 'Requests are waiting longer than usual.' },
		delayed: { label: 'Delayed', color: 'var(--warning-text)', detail: 'Background processing appears to have stalled.' },
		offline: { label: 'Offline', color: 'var(--danger-text)', detail: 'GeoQuery cannot be reached right now.' }
	} as const;

	let statusKey = $derived<keyof typeof STATUS_TEXT | null>(
		statusFailed ? 'offline' : (status?.state ?? null)
	);
</script>

<Seo title="Statistics" description="Usage statistics for AidData GeoQuery: requests and results extracted, turnaround times, and the datasets and boundaries most often requested." />

{#snippet statusBar(segments: Segment[], total: number, label: string)}
	<div
		class="flex h-3 w-full overflow-hidden rounded-full bg-muted"
		role="img"
		aria-label="{label}: {segments.map((s) => `${s.label} ${fmt(s.value)}`).join(', ')}"
	>
		{#each segments as s (s.label)}
			{#if total > 0 && s.value > 0}
				<div style="width: {(s.value / total) * 100}%; min-width: 3px; background: {s.color}"></div>
			{/if}
		{/each}
	</div>
	<dl class="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3">
		{#each segments as s (s.label)}
			<div class="flex items-center gap-2 text-sm">
				<span class="size-2.5 shrink-0 rounded-sm" style="background: {s.color}" aria-hidden="true"></span>
				<dt class="text-muted-foreground">{s.label}</dt>
				<dd class="ml-auto font-ui font-bold tabular-nums">{fmt(s.value)}</dd>
			</div>
		{/each}
	</dl>
{/snippet}

{#snippet toggle<T extends string>(options: readonly (readonly [T, string])[], current: T, set: (v: T) => void)}
	<div class="flex overflow-hidden rounded-md border">
		{#each options as [value, text] (value)}
			<button
				class="min-h-8 px-3 py-1.5 font-ui text-xs font-bold transition-colors {current === value
					? 'bg-background text-foreground'
					: 'bg-muted text-muted-foreground hover:text-foreground'}"
				aria-pressed={current === value}
				onclick={() => set(value)}
			>
				{text}
			</button>
		{/each}
	</div>
{/snippet}

{#snippet topList(title: string, rows: { title: string; requests: number }[] | undefined)}
	<div>
		<h3 class="mb-3 text-sm font-bold">{title}</h3>
		{#if rows?.length}
			{@const max = rows[0].requests}
			<ol class="flex flex-col gap-2">
				{#each rows as row, i (row.title)}
					<li class="grid grid-cols-[1.5rem_1fr_auto] items-center gap-x-2 text-sm">
						<span class="font-ui text-xs tabular-nums text-muted-foreground">{i + 1}</span>
						<span class="min-w-0">
							<span class="block truncate" title={row.title}>{row.title}</span>
							<span class="mt-1 block h-1 rounded-full bg-muted" aria-hidden="true">
								<span class="block h-1 rounded-full" style="width: {(row.requests / max) * 100}%; background: var(--chart-1)"></span>
							</span>
						</span>
						<span class="font-ui font-bold tabular-nums">{fmt(row.requests)}</span>
					</li>
				{/each}
			</ol>
		{:else}
			<p class="text-sm text-muted-foreground">Not enough requests yet.</p>
		{/if}
	</div>
{/snippet}

<div class="mx-auto max-w-5xl px-4 py-8">
	<!-- Service status -->
	<section
		aria-label="GeoQuery status"
		class="mb-6 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border bg-card px-4 py-3"
	>
		<div class="flex items-center gap-2">
			<span class="text-sm font-bold">GeoQuery status</span>
			{#if statusKey}
				{@const s = STATUS_TEXT[statusKey]}
				<span class="inline-flex items-center gap-1.5 font-ui text-sm font-bold" style="color: {s.color}" role="status">
					<span class="size-2.5 rounded-full" style="background: {s.color}" aria-hidden="true"></span>
					{s.label}
				</span>
			{:else}
				<span class="text-sm text-muted-foreground">Checking…</span>
			{/if}
		</div>
		{#if statusKey}
			<p class="text-sm text-muted-foreground">
				{STATUS_TEXT[statusKey].detail}
				{#if status && statusKey !== 'offline'}
					{status.unfinished_requests === 0
						? 'No requests waiting.'
						: `${fmt(status.unfinished_requests)} in progress; oldest waiting ${duration(status.oldest_wait_seconds)}.`}
				{/if}
			</p>
		{/if}
	</section>

	<div class="mb-6 flex flex-wrap items-start justify-between gap-4">
		<div>
			<h1 class="text-h2">Statistics</h1>
			<p class="mt-1 text-sm text-muted-foreground">How GeoQuery is being used</p>
		</div>
		<div class="flex items-center gap-3">
			{#if stats}
				<span class="rounded-md border bg-muted px-3 py-1 text-xs text-muted-foreground">
					Figures as of {stats.generated_at}
				</span>
			{/if}
			<Button variant="ghost" size="sm" onclick={refresh} disabled={loading}>
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
		<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
			{#each Array(4) as _, i (i)}
				<Card><CardContent class="py-6"><div class="h-12 animate-pulse rounded bg-muted"></div></CardContent></Card>
			{/each}
		</div>
	{:else if stats}
		<!-- Headline figures -->
		<div class="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
			{#each headline as h (h.label)}
				<Card>
					<CardContent class="pt-5">
						<div class="text-xs font-bold text-muted-foreground">{h.label}</div>
						<div class="mt-1 font-ui text-h2 font-bold tabular-nums">
							{h.value == null ? '—' : fmt(h.value)}
						</div>
						{#if h.note}
							<div class="mt-1 text-xs text-muted-foreground">{h.note}</div>
						{/if}
					</CardContent>
				</Card>
			{/each}
		</div>

		<!-- Requests -->
		<Card class="mb-6">
			<CardHeader>
				<CardTitle>Requests</CardTitle>
			</CardHeader>
			<CardContent class="flex flex-col gap-6">
				<div class="grid gap-6 md:grid-cols-[3fr_2fr]">
					<div>
						<div class="mb-2 text-xs font-bold text-muted-foreground">
							All {fmt(stats.total)} requests by status
						</div>
						{@render statusBar(requestSegments, stats.total, 'Requests by status')}
					</div>
					<dl class="grid grid-cols-2 content-start gap-4 text-sm">
						<div>
							<dt class="text-xs font-bold text-muted-foreground">Last 7 days</dt>
							<dd class="mt-1">
								<span class="font-ui text-lg font-bold tabular-nums">{fmt(lastDays(stats.time_series?.submit_time?.day, 7))}</span>
								submitted
							</dd>
							<dd>
								<span class="font-ui font-bold tabular-nums">{fmt(lastDays(stats.time_series?.complete_time?.day, 7))}</span>
								completed
							</dd>
						</div>
						<div>
							<dt class="text-xs font-bold text-muted-foreground">
								Turnaround{stats.turnaround ? `, last ${stats.turnaround.days} days` : ''}
							</dt>
							{#if stats.turnaround?.count}
								<dd class="mt-1">
									<span class="font-ui text-lg font-bold tabular-nums">{duration(stats.turnaround.median_seconds)}</span>
									typical
								</dd>
								<dd>
									<span class="font-ui font-bold tabular-nums">{duration(stats.turnaround.p90_seconds)}</span>
									for 9 in 10
								</dd>
								<dd class="text-xs text-muted-foreground">over {fmt(stats.turnaround.count)} requests</dd>
							{:else}
								<dd class="mt-1 text-muted-foreground">No requests completed recently</dd>
							{/if}
						</div>
					</dl>
				</div>

				<div>
					<div class="mb-3 flex flex-wrap items-center justify-between gap-3">
						<h3 class="text-sm font-bold">Over time</h3>
						<div class="flex flex-wrap items-center gap-2">
							{@render toggle(
								[
									['submit_time', 'Submitted'],
									['complete_time', 'Completed']
								] as const,
								field,
								(v) => (field = v)
							)}
							{@render toggle(
								periods.map((p) => [p, p[0].toUpperCase() + p.slice(1)] as const),
								period,
								(v) => (period = v)
							)}
						</div>
					</div>
					<BarChart data={requestSeries} label="requests" series={1} title="Requests over time" />
				</div>
			</CardContent>
		</Card>

		<!-- Extract tasks -->
		<Card class="mb-6">
			<CardHeader>
				<CardTitle>Extract tasks</CardTitle>
				<p class="text-sm text-muted-foreground">
					Each task extracts one dataset period for one area. Tasks are shared between requests,
					so a result is computed once and reused.
				</p>
			</CardHeader>
			<CardContent class="flex flex-col gap-6">
				<div class="grid gap-6 md:grid-cols-[3fr_2fr]">
					<div>
						<div class="mb-2 text-xs font-bold text-muted-foreground">
							All {fmt(stats.extract_counts?.total)} tasks by status
						</div>
						{@render statusBar(taskSegments, stats.extract_counts?.total ?? 0, 'Extract tasks by status')}
					</div>
					<dl class="grid grid-cols-2 content-start gap-4 text-sm">
						<div>
							<dt class="text-xs font-bold text-muted-foreground">Completed today</dt>
							<dd class="mt-1 font-ui text-lg font-bold tabular-nums">{fmt(lastDays(stats.extract_time_series?.day, 1))}</dd>
						</div>
						<div>
							<dt class="text-xs font-bold text-muted-foreground">Last 7 days</dt>
							<dd class="mt-1 font-ui text-lg font-bold tabular-nums">{fmt(lastDays(stats.extract_time_series?.day, 7))}</dd>
						</div>
					</dl>
				</div>

				<div>
					<div class="mb-3 flex flex-wrap items-center justify-between gap-3">
						<h3 class="text-sm font-bold">Completions over time</h3>
						{@render toggle(
							periods.map((p) => [p, p[0].toUpperCase() + p.slice(1)] as const),
							extPeriod,
							(v) => (extPeriod = v)
						)}
					</div>
					<BarChart data={extractSeries} label="tasks" series={3} title="Extract task completions over time" />
				</div>
			</CardContent>
		</Card>

		<!-- Most requested -->
		<Card>
			<CardHeader>
				<CardTitle>Most requested</CardTitle>
				<p class="text-sm text-muted-foreground">
					By number of requests including each, since the current version of GeoQuery launched.
				</p>
			</CardHeader>
			<CardContent class="grid gap-8 md:grid-cols-2">
				{@render topList('Datasets', stats.top_datasets)}
				{@render topList('Boundary sets', stats.top_boundary_sets)}
			</CardContent>
		</Card>
	{/if}
</div>
