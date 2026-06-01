<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { Button } from '$lib/components/ui/button';
	import { Home, ArrowLeft, MapPin } from '@lucide/svelte';

	const status = $derived(page.status);
	const message = $derived(page.error?.message ?? '');

	const config = $derived.by(() => {
		switch (status) {
			case 404:
				return {
					heading: 'Page not found',
					description: "The page you're looking for doesn't exist or may have been moved.",
					showBack: true,
				};
			case 403:
				return {
					heading: 'Access denied',
					description: "You don't have permission to view this page.",
					showBack: true,
				};
			case 500:
				return {
					heading: 'Something went wrong',
					description: 'An unexpected error occurred on our end. Please try again in a moment.',
					showBack: false,
				};
			default:
				return {
					heading: `Error ${status}`,
					description: message || 'An unexpected error occurred.',
					showBack: true,
				};
		}
	});
</script>

<div class="flex min-h-[calc(100vh-5rem)] flex-col items-center justify-center px-4 py-16 text-center">
	<div class="mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
		<MapPin class="h-8 w-8 text-muted-foreground" />
	</div>

	<div class="text-7xl font-bold text-muted-foreground/30 mb-2">{status}</div>

	<h1 class="mb-3 text-2xl font-semibold text-foreground">{config.heading}</h1>

	<p class="mb-8 max-w-md text-muted-foreground">{config.description}</p>

	<div class="flex items-center gap-3">
		{#if config.showBack}
			<Button variant="outline" onclick={() => history.back()}>
				<ArrowLeft class="mr-2 h-4 w-4" />
				Go back
			</Button>
		{/if}
		<Button onclick={() => goto('/')}>
			<Home class="mr-2 h-4 w-4" />
			Back to Map
		</Button>
	</div>
</div>