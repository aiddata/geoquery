<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { openSidebar, currentStep, type Step } from '$lib/stores/ui';
	import { CircleHelp, History, MapPin, Star, ClipboardList } from '@lucide/svelte';

	interface Props {
		logoUrl?: string;
		showSteps?: boolean;
	}

	let { logoUrl = 'https://www.aiddata.org/assets/img/aiddata-main-logo.png', showSteps = true }: Props = $props();

	const steps: { id: Step; label: string; icon: typeof MapPin }[] = [
		{ id: 'map', label: '1. Select Boundary', icon: MapPin },
		{ id: 'search', label: '2. Customize Datasets', icon: Star },
		{ id: 'review', label: '3. Review Request', icon: ClipboardList }
	];
</script>

<header class="sticky top-0 z-50 w-full border-b bg-background">
	<!-- Main Header -->
	<div class="flex h-16 items-center justify-between px-4">
		<!-- Logo -->
		<a href="https://www.aiddata.org/geoquery" class="flex items-center">
			<img src={logoUrl} alt="AidData GeoQuery" class="h-10" />
		</a>

		<!-- Navigation Buttons -->
		<div class="flex items-center gap-2">
			<Button variant="ghost" onclick={() => openSidebar('help')}>
				<CircleHelp />
				Help
			</Button>

			<Button variant="ghost" href="/requests">
				<History />
				Past Requests
			</Button>
		</div>
	</div>

	<!-- Step Indicator (only on workflow pages) -->
	{#if showSteps}
		<div class="flex h-12 items-center justify-between border-t bg-muted/50 px-4">
			<div class="flex items-center gap-2">
				{#each steps as step, i}
					{#if i > 0}
						<span class="text-muted-foreground">/</span>
					{/if}
					<span
						class="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium
							{$currentStep === step.id
							? 'bg-primary text-primary-foreground'
							: 'text-muted-foreground'}"
					>
						<step.icon class="h-4 w-4" />
						{step.label}
					</span>
				{/each}
			</div>

			<div class="text-sm text-muted-foreground">
				Powered by
				<a href="https://www.aiddata.org" class="font-medium hover:underline">AidData</a>,
				a research lab at
				<a href="https://www.wm.edu/" class="font-medium hover:underline">William & Mary</a>
			</div>
		</div>
	{/if}
</header>
