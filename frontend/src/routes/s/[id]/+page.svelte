<script lang="ts">
	import Seo from '#lib/components/layout/Seo.svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { fetchSharedRecipe } from '#lib/api.js';
	import { loadSharedRecipe, requestInProgress } from '#lib/loadRecipe.js';
	import { get } from 'svelte/store';
	import { customizeHref } from '#lib/stores/selection.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';

	// A share link (GEO-126): loads the shared request into this tab, replacing
	// the one being built after a confirm, and goes on to Customize.
	type Shared = Awaited<ReturnType<typeof fetchSharedRecipe>>;

	// Raw: the loader copies it with structuredClone, which a $state proxy breaks
	let shared = $state.raw<Shared | null>(null);
	let error = $state<string | null>(null);
	let confirmReplace = $state(false);

	// The dialog's answer, so closing it (Escape, outside click) counts as keeping
	let decided = false;
	function keepCurrent() {
		decided = true;
		confirmReplace = false;
		goto(get(customizeHref) ?? '/', { replace: true });
	}
	function openShared() {
		decided = true;
		confirmReplace = false;
		if (shared) open(shared);
	}

	function open(result: Shared) {
		try {
			goto(loadSharedRecipe(result), { replace: true });
		} catch (e) {
			error = e instanceof Error ? e.message : "This link can't be opened.";
		}
	}

	onMount(async () => {
		try {
			shared = await fetchSharedRecipe(page.params.id as string);
		} catch (e) {
			error = e instanceof Error ? e.message : "This link can't be opened.";
			return;
		}
		if (requestInProgress()) confirmReplace = true;
		else open(shared);
	});
</script>

<Seo title="Shared request" noindex />

<div class="container mx-auto max-w-2xl px-4 py-16">
	{#if error}
		<h1 class="mb-2 text-h3">This link can't be opened</h1>
		<p class="text-muted-foreground" role="alert">{error}</p>
		<Button class="mt-4" variant="outline" onclick={() => goto('/')}>Start a new request</Button>
	{:else if confirmReplace}
		<h1 class="mb-2 text-h3">Open a shared request</h1>
		<p class="text-muted-foreground">You have a request in progress.</p>
	{:else}
		<p class="text-muted-foreground" role="status">Opening the shared request…</p>
	{/if}
</div>

<Dialog.Root
	bind:open={confirmReplace}
	onOpenChange={(isOpen) => {
		if (!isOpen && !decided) keepCurrent();
	}}
>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>Replace your current request?</Dialog.Title>
			<Dialog.Description>
				Opening this link replaces the boundaries and datasets you've chosen so far with the shared request's.
			</Dialog.Description>
		</Dialog.Header>
		<Dialog.Footer>
			<Button variant="outline" onclick={keepCurrent}>Keep current request</Button>
			<Button onclick={openShared}>Open shared request</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
