<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import UserMenu from '#lib/components/layout/UserMenu.svelte';
	import ThemeMenu from '#lib/components/layout/ThemeMenu.svelte';
	import { openSidebar, currentStep, type Step } from '#lib/stores/ui.js';
	import { features } from '#lib/stores/features.js';
	import { CircleHelp, History, BookOpen, Info, Map } from '@lucide/svelte';
	import aiddataLogo from '#lib/assets/aiddata_logo.svg';
	import aiddataLogoWhite from '#lib/assets/aiddata_logo_white.png';
	import geoqueryText from '#lib/assets/geoquery_text.svg';

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
		<div class="flex shrink-0 items-center gap-3">
			<!-- AidData's own white-lettered logo for dark mode; the triangles keep their colours. -->
			<a
				href="https://www.aiddata.org/"
				target="_blank"
				rel="noopener noreferrer"
				aria-label="AidData (opens in a new tab)"
			>
				<img src={aiddataLogo} alt="" class="h-[2.3rem] w-auto sm:h-[2.875rem] dark:hidden" />
				<img src={aiddataLogoWhite} alt="" class="hidden h-[2.3rem] w-auto sm:h-[2.875rem] dark:block" />
			</a>
			<span class="hidden h-10 w-px bg-border md:block" aria-hidden="true"></span>
			<a href="/" class="hidden md:block" aria-label="GeoQuery home">
				<img src={geoqueryText} alt="" class="h-10 w-auto brightness-0 dark:invert" />
			</a>
		</div>

		<!-- Navigation Buttons -->
		<div class="flex items-center gap-2">
			<Button variant="ghost" href="https://www.aiddata.org/geoquery" target="_blank" rel="noopener noreferrer">
				<Info />
				<span class="sr-only sm:not-sr-only">About</span>
			</Button>

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
