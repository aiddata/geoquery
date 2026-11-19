<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';
	import { createShareLink } from '#lib/api.js';
	import { Check, Link } from '@lucide/svelte';

	// "Copy share link" (GEO-126): saves the request's recipe and copies a short
	// link to it. Anyone who opens the link gets exactly what was shared, and can
	// change it before submitting their own. Requests with a custom upload can't
	// be shared: the button stays focusable (aria-disabled) so its tooltip says why.
	interface Props {
		/** The recipe to share (lib/recipe.ts), or a promise of one */
		getRecipe: () => unknown | Promise<unknown>;
		/** Set when the request can't be shared, as the tooltip's text */
		unavailable?: string | null;
		size?: 'sm' | 'default';
		class?: string;
	}

	let { getRecipe, unavailable = null, size = 'sm', class: className = '' }: Props = $props();

	let busy = $state(false);
	let link = $state<string | null>(null);
	let copied = $state(false);
	let error = $state<string | null>(null);
	let timer: ReturnType<typeof setTimeout> | undefined;

	async function share() {
		if (unavailable || busy) return;
		busy = true;
		error = null;
		try {
			const { path } = await createShareLink(await getRecipe());
			link = new URL(path, window.location.origin).toString();
			try {
				await navigator.clipboard.writeText(link);
				copied = true;
				clearTimeout(timer);
				timer = setTimeout(() => (copied = false), 3000);
			} catch {
				// No clipboard access: the link is shown below to copy by hand
				copied = false;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : "The link couldn't be created.";
		} finally {
			busy = false;
		}
	}
</script>

<div class="flex flex-col gap-2 {className}">
	{#if unavailable}
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<Button {...props} variant="outline" {size} aria-disabled="true" class="cursor-not-allowed self-start opacity-50">
						<Link />
						Copy share link
					</Button>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content>{unavailable}</Tooltip.Content>
		</Tooltip.Root>
	{:else}
		<Button variant="outline" {size} class="self-start" onclick={share} disabled={busy}>
			{#if copied}<Check />{:else}<Link />{/if}
			{busy ? 'Creating link…' : copied ? 'Link copied' : 'Copy share link'}
		</Button>
		<span class="sr-only" role="status">{copied ? 'Share link copied to the clipboard' : ''}</span>
		{#if link && !copied}
			<Input readonly value={link} aria-label="Share link" class="h-8 text-xs" onfocus={(e) => e.currentTarget.select()} />
		{/if}
	{/if}
	{#if error}
		<p class="text-sm text-danger-text" role="alert">{error}</p>
	{/if}
</div>
