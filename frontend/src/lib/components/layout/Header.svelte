<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import UserMenu from '$lib/components/layout/UserMenu.svelte';
	import ThemeMenu from '$lib/components/layout/ThemeMenu.svelte';
	import { openSidebar, currentStep, type Step } from '$lib/stores/ui';
	import { features } from '$lib/stores/features';
	import { CircleHelp, History, BookOpen, Map } from '@lucide/svelte';
	import aiddataTriangles from '$lib/assets/aiddata_triangles.svg';
	import aiddataWordmark from '$lib/assets/aiddata_wordmark.svg';
	import geoqueryText from '$lib/assets/geoquery_text.png';

	interface Props {
		showSteps?: boolean;
	}

	let { showSteps = true }: Props = $props();

	const steps: { id: Step; label: string }[] = [
		{ id: 'map', label: '1. Select Boundary' },
		{ id: 'search', label: '2. Customize Datasets' },
		{ id: 'review', label: '3. Review Request' }
	];
</script>

<header class="sticky top-0 z-50 w-full bg-card shadow-card">
	<!-- Main Header -->
	<div class="flex min-h-20 items-center justify-between px-4">
		<!-- Logo -->
		<a href="/" class="flex shrink-0 items-start gap-3" aria-label="AidData GeoQuery home">
			<img src={aiddataTriangles} alt="" class="h-10 w-auto" />
			<img src={aiddataWordmark} alt="" class="hidden h-10 w-auto xl:block dark:brightness-0 dark:invert" />
			<span class="hidden h-10 w-px bg-border xl:block" aria-hidden="true"></span>
			<img src={geoqueryText} alt="" class="hidden h-10 w-auto md:block dark:brightness-0 dark:invert" />
		</a>

		<!-- Navigation Buttons -->
		<div class="flex items-center gap-2">
			<Button variant="ghost" href="https://aiddata.github.io/geoquery/" target="_blank" rel="noopener noreferrer">
				<BookOpen />
				<span class="sr-only sm:not-sr-only">Docs</span>
			</Button>

			<Button variant="ghost" onclick={() => openSidebar('help')}>
				<CircleHelp />
				<span class="sr-only sm:not-sr-only">Help</span>
			</Button>

			<Button variant="ghost" href="/requests">
				<History />
				<span class="sr-only sm:not-sr-only">Past Requests</span>
			</Button>

			<ThemeMenu />
			<UserMenu />
		</div>
	</div>

	<!-- Step Indicator (only on workflow pages) -->
	{#if showSteps}
		<div class="flex min-h-12 items-center justify-between bg-band px-4">
			<div class="flex items-center gap-1 sm:gap-2">
				{#each steps as step, i}
					{#if i > 0}
						<span class="text-muted-foreground">/</span>
					{/if}
					<span
						class="flex items-center rounded-md px-2 py-1.5 text-sm font-bold sm:px-3
							{$currentStep === step.id
							? 'bg-primary text-primary-foreground'
							: 'text-muted-foreground'}"
					>
						{step.label}
					</span>
				{/each}
			</div>

			{#if $features.has('visualize')}
				<Button
					variant="ghost"
					size="sm"
					href="/viz/explore"
					class="hidden font-body text-muted-foreground lg:inline-flex"
				>
					<Map />
					Map and Visualize Data
					<Badge variant="new">new</Badge>
				</Button>
			{/if}
		</div>
	{/if}
</header>
