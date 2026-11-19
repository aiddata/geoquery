<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.js';
	import { auth, signOut } from '#lib/stores/auth.js';
	import { loginWithGitHub } from '#lib/allauth.js';
	import { History, LogIn, LogOut, UserRound } from '@lucide/svelte';

	let signingIn = $state(false);

	async function handleSignIn() {
		signingIn = true;
		try {
			await loginWithGitHub(page.url.pathname);
		} catch {
			signingIn = false;
		}
	}

	async function handleSignOut() {
		await signOut();
		goto('/');
	}
</script>

{#if $auth.status === 'authenticated' || $auth.status === 'anonymous'}
	<DropdownMenu.Root>
		<DropdownMenu.Trigger>
			{#snippet child({ props })}
				<Button {...props} variant="ghost">
					<UserRound />
					<span class="sr-only max-w-40 truncate sm:not-sr-only">
						Account
					</span>
				</Button>
			{/snippet}
		</DropdownMenu.Trigger>
		<DropdownMenu.Content align="end" class="w-56">
			{#if $auth.status === 'authenticated'}
				<DropdownMenu.Label class="truncate font-normal">
					{$auth.user.email}
				</DropdownMenu.Label>
				<DropdownMenu.Separator />
				<DropdownMenu.Item onclick={() => goto('/account')}>
					<UserRound />
					Account
				</DropdownMenu.Item>
				<DropdownMenu.Item onclick={() => goto('/requests')}>
					<History />
					My Requests
				</DropdownMenu.Item>
				<DropdownMenu.Separator />
				<DropdownMenu.Item onclick={handleSignOut}>
					<LogOut />
					Sign out
				</DropdownMenu.Item>
			{:else}
				<!-- Signed out: sign in, or get an emailed link to past requests,
				     which needs no account -->
				<DropdownMenu.Item onclick={handleSignIn} disabled={signingIn}>
					<LogIn />
					Sign in
				</DropdownMenu.Item>
				<DropdownMenu.Item onclick={() => goto('/requests')}>
					<History />
					Past Requests
				</DropdownMenu.Item>
			{/if}
		</DropdownMenu.Content>
	</DropdownMenu.Root>
{/if}
