<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';
	import { createShareLink } from '#lib/api.js';
	import { Check, Link } from '@lucide/svelte';

	// "Copy share link" (GEO-126): saves the request's recipe and copies a short
	// link to it. Anyone who opens the link gets exactly what was shared, and can
	// change it before submitting their own. Requests with a custom upload can't
	// be shared: the button stays focusable (aria-disabled) so its tooltip says why.
	// Only as tall as the button: the explanation is its tooltip, and the link
	// itself is shown (small, beside the button) only when it couldn't be copied.
	interface Props {
		/** The recipe to share (lib/recipe.ts), or a promise of one */
		getRecipe: () => unknown | Promise<unknown>;
		/** Set when the request can't be shared, as the tooltip's text */
		unavailable?: string | null;
		/** The tooltip when it can be shared */
		hint?: string;
		/**
		 * The request as it is now (any string that changes when it does), for a
		 * request that can still be edited. A link is a snapshot, so once the
		 * request changes after copying, the button offers an updated link.
		 */
		current?: string | null;
		size?: 'sm' | 'default';
		class?: string;
	}

	let {
		getRecipe,
		unavailable = null,
		hint = 'Anyone with the link can open a copy of this request as it is now',
		current = null,
		size = 'sm',
		class: className = ''
	}: Props = $props();

	let busy = $state(false);
	let link = $state<string | null>(null);
	let copied = $state(false);
	/** The clipboard wasn't available, so the link is shown to copy by hand */
	let manual = $state(false);
	let error = $state<string | null>(null);
	/** `current` when the link was made */
	let sharedFor = $state<string | null>(null);
	/** The request changed after its link was made: that link opens the earlier version */
	const stale = $derived(!!link && current !== null && sharedFor !== current);
	let timer: ReturnType<typeof setTimeout> | undefined;

	async function share() {
		if (unavailable || busy) return;
		busy = true;
		error = null;
		manual = false;
		const snapshot = current;
		try {
			const { path } = await createShareLink(await getRecipe());
			link = new URL(path, window.location.origin).toString();
			sharedFor = snapshot;
			try {
				await navigator.clipboard.writeText(link);
				copied = true;
				clearTimeout(timer);
				timer = setTimeout(() => (copied = false), 3000);
			} catch {
				copied = false;
				manual = true;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : "The link couldn't be created.";
		} finally {
			busy = false;
		}
	}
</script>

<div class="flex min-w-0 items-center gap-3 {className}">
	<Tooltip.Root>
		<Tooltip.Trigger>
			{#snippet child({ props })}
				{#if unavailable}
					<Button {...props} variant="outline" {size} aria-disabled="true" class="cursor-not-allowed opacity-50">
						<Link />
						Copy share link
					</Button>
				{:else}
					<Button {...props} variant="outline" {size} onclick={share} disabled={busy}>
						{#if copied && !stale}<Check />{:else}<Link />{/if}
						{busy ? 'Creating link…' : copied && !stale ? 'Link copied' : stale ? 'Copy updated link' : 'Copy share link'}
					</Button>
				{/if}
			{/snippet}
		</Tooltip.Trigger>
		<Tooltip.Content>
			{unavailable ??
				(stale
					? "You've changed this request since copying its link. The earlier link still opens it as it was."
					: hint)}
		</Tooltip.Content>
	</Tooltip.Root>
	<span class="sr-only" role="status">{copied ? 'Share link copied to the clipboard' : ''}</span>
	{#if link && manual && !stale}
		<!-- Beside the button, one line: the clipboard wasn't available -->
		<a href={link} title="Copy this link" class="min-w-0 truncate text-xs text-link underline select-all hover:text-link-hover">{link}</a>
	{/if}
	{#if error}
		<p class="min-w-0 truncate text-xs text-danger-text" role="alert" title={error}>{error}</p>
	{/if}
</div>
