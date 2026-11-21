<script lang="ts">
	import Seo from '#lib/components/layout/Seo.svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { fetchRequestDetail, fetchRequestRecipe } from '#lib/api.js';
	import { loadRequestTemplate } from '#lib/loadRecipe.js';
	import { Button } from '#lib/components/ui/button/index.js';

	// "Duplicate request › Open in a new tab" (GEO-146) opens this in a tab of
	// its own, so it loads the request straight away: there's no request being
	// built here to ask about replacing. (A tab opened from another can start
	// with a copy of the opener's request, from sessionStorage; it's replaced.)
	let error = $state<string | null>(null);

	onMount(async () => {
		const id = page.params.id as string;
		try {
			const [detail, recipe] = await Promise.all([fetchRequestDetail(id), fetchRequestRecipe(id)]);
			goto(loadRequestTemplate(recipe, detail.name || 'Unnamed Request'), { replace: true });
		} catch (e) {
			error = e instanceof Error ? e.message : "This request couldn't be duplicated.";
		}
	});
</script>

<Seo title="Duplicate request" noindex />

<div class="container mx-auto max-w-2xl px-4 py-16">
	{#if error}
		<h1 class="mb-2 text-h3">This request can't be duplicated</h1>
		<p class="text-muted-foreground" role="alert">{error}</p>
		<div class="mt-4 flex flex-wrap gap-2">
			<Button variant="outline" href="/requests/{page.params.id}">Back to the request</Button>
			<Button variant="outline" href="/">Start a new request</Button>
		</div>
	{:else}
		<p class="text-muted-foreground" role="status">Duplicating the request…</p>
	{/if}
</div>
