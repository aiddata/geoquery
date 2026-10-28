<script lang="ts">
	import { page } from '$app/state';
	import { features } from '$lib/stores/features';
	import { Button } from '$lib/components/ui/button';
	import { FlaskConical, Home, FileText } from '@lucide/svelte';

	// /viz is a beta feature (see $lib/stores/features). Children don't render,
	// and so don't fetch, until access is confirmed. Old documentation pages and
	// chats link here, so the fallback points somewhere useful.
	let { children } = $props();

	let requestId = $derived(page.params.id);
</script>

{#if !$features.ready}
	<div class="flex min-h-[calc(100vh-5rem)] items-center justify-center text-sm text-muted-foreground">
		Loading…
	</div>
{:else if $features.has('visualize')}
	{@render children()}
{:else}
	<div class="flex min-h-[calc(100vh-5rem)] flex-col items-center justify-center px-4 py-16 text-center">
		<div class="mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
			<FlaskConical class="h-8 w-8 text-muted-foreground" />
		</div>

		<h1 class="mb-3 text-h2 text-foreground">Visualization is in beta</h1>

		<p class="mb-8 max-w-md text-muted-foreground">
			Mapping and visualizing data in GeoQuery isn't available to everyone yet.
			{#if requestId}
				Your request's results can still be downloaded from its details page.
			{/if}
		</p>

		<div class="flex items-center gap-3">
			{#if requestId}
				<Button variant="outline" href={`/requests/${requestId}`}>
					<FileText />
					View Request
				</Button>
			{/if}
			<Button href="/">
				<Home />
				Back to Map
			</Button>
		</div>
	</div>
{/if}
