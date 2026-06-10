<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { openSidebar, currentStep, type Step } from '$lib/stores/ui';
	import { CircleHelp, History, MapPin, Star, ClipboardList, BookOpen, Map } from '@lucide/svelte';
	import geoqueryLogo from '$lib/assets/aiddata_geoquery_wordmark.png';

	interface Props {
		showSteps?: boolean;
	}

	let { showSteps = true }: Props = $props();

	const steps: { id: Step; label: string; icon: typeof MapPin }[] = [
		{ id: 'map', label: '1. Select Boundary', icon: MapPin },
		{ id: 'search', label: '2. Customize Datasets', icon: Star },
		{ id: 'review', label: '3. Review Request', icon: ClipboardList }
	];
</script>

<header class="sticky top-0 z-50 w-full border-b bg-background">
	<!-- Main Header -->
	<div class="flex h-20 items-center justify-between px-4">
		<!-- Logo -->
		<a href="/" class="flex items-center -ml-7">
			<img src={geoqueryLogo} alt="GeoQuery" class="h-14 w-auto sm:h-18 md:h-24" />
		</a>

		<!-- Navigation Buttons -->
		<div class="flex items-center gap-2">
			<Button variant="ghost" href="https://aiddata.github.io/geoquery-update/" target="_blank" rel="noopener noreferrer">
				<BookOpen />
				<span class="hidden sm:inline">Docs</span>
			</Button>

<Button variant="ghost" onclick={() => openSidebar('help')}>
				<CircleHelp />
				<span class="hidden sm:inline">Help</span>
			</Button>

			<Button variant="ghost" href="/requests">
				<History />
				<span class="hidden sm:inline">Past Requests</span>
			</Button>
		</div>
	</div>

	<!-- Step Indicator (only on workflow pages) -->
	{#if showSteps}
		<div class="flex h-12 items-center justify-between border-t bg-muted/50 px-4">
			<div class="flex items-center gap-1 sm:gap-2">
				{#each steps as step, i}
					{#if i > 0}
						<span class="text-muted-foreground">/</span>
					{/if}
					<span
						class="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm font-medium sm:px-3
							{$currentStep === step.id
							? 'bg-primary text-primary-foreground'
							: 'text-muted-foreground'}"
					>
						<step.icon class="h-4 w-4 shrink-0" />
						<span class="hidden sm:inline">{step.label}</span>
					</span>
				{/each}
			</div>

			<a
				href="/viz/explore"
				class="hidden items-center gap-1.5 rounded-md px-2 py-1 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground lg:flex mr-4"
			>
				<Map class="h-4 w-4 shrink-0" />
				<span class="relative">
					Map and Visualize Data
					<span class="absolute -top-2.5 -right-6 rounded bg-blue-500 px-1 py-px text-[9px] font-bold uppercase leading-none tracking-wide text-white">new</span>
				</span>
			</a>
		</div>
	{/if}
</header>
