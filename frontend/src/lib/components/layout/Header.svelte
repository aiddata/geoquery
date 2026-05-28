<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { openSidebar, currentStep, type Step } from '$lib/stores/ui';
	import { CircleHelp, History, MapPin, Star, ClipboardList } from '@lucide/svelte';
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
			<img src={geoqueryLogo} alt="GeoQuery" class="h-24" />
		</a>

		<!-- Navigation Buttons -->
		<div class="flex items-center gap-2">
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

			<div class="hidden text-sm text-muted-foreground lg:block">
				Powered by
				<a href="https://www.aiddata.org" class="font-medium hover:underline">AidData</a>,
				a research lab at
				<a href="https://www.wm.edu/" class="font-medium hover:underline">William & Mary</a>
			</div>
		</div>
	{/if}
</header>
