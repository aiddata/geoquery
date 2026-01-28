<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import { openSidebar, currentStep, type Step } from '$lib/stores/ui';
	import { CircleHelp, History, ListTodo, MapPin, Star, ClipboardList } from '@lucide/svelte';

	interface Props {
		cartCount?: number;
		logoUrl?: string;
		showSteps?: boolean;
	}

	let { cartCount = 0, logoUrl = 'https://www.aiddata.org/assets/img/aiddata-main-logo.png', showSteps = true }: Props = $props();

	const steps: { id: Step; label: string; icon: typeof MapPin }[] = [
		{ id: 'map', label: '1. Select Boundary', icon: MapPin },
		{ id: 'search', label: '2. Customize Datasets', icon: Star },
		{ id: 'checkout', label: '3. Review Request', icon: ClipboardList }
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
				<CircleHelp class="mr-1 h-4 w-4" />
				Help
			</Button>

			<Button variant="ghost" href="/requests">
				<History class="mr-1 h-4 w-4" />
				Past Requests
			</Button>

			<Button
				variant={cartCount > 0 ? 'default' : 'ghost'}
				onclick={() => openSidebar('cart')}
				disabled={cartCount === 0}
				class="relative"
			>
				<ListTodo class="mr-1 h-4 w-4" />
				Submit Request
				{#if cartCount > 0}
					<Badge variant="secondary" class="ml-2">{cartCount}</Badge>
				{/if}
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
					<button
						class="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors
							{$currentStep === step.id
							? 'bg-primary text-primary-foreground'
							: 'text-muted-foreground hover:text-foreground'}"
						disabled
					>
						<step.icon class="h-4 w-4" />
						{step.label}
					</button>
				{/each}
			</div>

			<div class="text-sm text-muted-foreground">
				Powered by
				<a href="https://www.aiddata.org" class="font-medium hover:underline">AidData</a>
				and
				<a href="https://www.wm.edu/" class="font-medium hover:underline">William & Mary's</a>
				<a href="https://www.wm.edu/offices/global-research/" class="font-medium hover:underline">
					Global Research Institute
				</a>
			</div>
		</div>
	{/if}
</header>
