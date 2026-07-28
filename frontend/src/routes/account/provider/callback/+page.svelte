<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import { auth, initAuth } from '$lib/stores/auth';
	import { loginWithGitHub } from '$lib/allauth';
	import { LoaderCircle, TriangleAlert } from '@lucide/svelte';

	// allauth redirects here after the OAuth round-trip; on failure it appends
	// ?error=... (this route is also HEADLESS_FRONTEND_URLS.socialaccount_login_error).
	let error = $state<string | null>(null);

	onMount(async () => {
		const errorParam = page.url.searchParams.get('error');
		if (errorParam) {
			error = page.url.searchParams.get('error_description') ?? errorParam;
			return;
		}
		await initAuth();
		if ($auth.status === 'authenticated') {
			goto(page.url.searchParams.get('next') ?? '/account', { replaceState: true });
		} else {
			error = 'Sign-in did not complete. Please try again.';
		}
	});
</script>

<div class="mx-auto flex max-w-md flex-col items-center px-4 py-16">
	{#if error}
		<Card.Root class="w-full">
			<Card.Header>
				<Card.Title class="flex items-center gap-2">
					<TriangleAlert class="h-5 w-5 text-destructive" />
					Sign-in failed
				</Card.Title>
				<Card.Description>{error}</Card.Description>
			</Card.Header>
			<Card.Footer class="gap-2">
				<Button onclick={() => loginWithGitHub('/account')}>Try again</Button>
				<Button variant="outline" href="/">Back to GeoQuery</Button>
			</Card.Footer>
		</Card.Root>
	{:else}
		<LoaderCircle class="h-8 w-8 animate-spin text-muted-foreground" />
		<p class="mt-4 text-sm text-muted-foreground">Completing sign-in…</p>
	{/if}
</div>
