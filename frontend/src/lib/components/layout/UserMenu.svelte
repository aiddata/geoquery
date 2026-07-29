<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Button } from '$lib/components/ui/button';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
	import { auth, signOut } from '$lib/stores/auth';
	import { loginWithGitHub } from '$lib/allauth';
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

{#if $auth.status === 'authenticated'}
	<DropdownMenu.Root>
		<DropdownMenu.Trigger>
			{#snippet child({ props })}
				<Button {...props} variant="ghost">
					<UserRound />
					<span class="hidden max-w-40 truncate sm:inline">
						{$auth.user.display || $auth.user.email}
					</span>
				</Button>
			{/snippet}
		</DropdownMenu.Trigger>
		<DropdownMenu.Content align="end" class="w-56">
			<DropdownMenu.Label class="truncate font-normal text-muted-foreground">
				{$auth.user.email}
			</DropdownMenu.Label>
			<DropdownMenu.Separator />
			<DropdownMenu.Item onclick={() => goto('/account')}>
				<UserRound class="mr-2 h-4 w-4" />
				Account
			</DropdownMenu.Item>
			<DropdownMenu.Item onclick={() => goto('/requests')}>
				<History class="mr-2 h-4 w-4" />
				My Requests
			</DropdownMenu.Item>
			<DropdownMenu.Separator />
			<DropdownMenu.Item onclick={handleSignOut}>
				<LogOut class="mr-2 h-4 w-4" />
				Sign out
			</DropdownMenu.Item>
		</DropdownMenu.Content>
	</DropdownMenu.Root>
{:else if $auth.status === 'anonymous'}
	<Button variant="ghost" onclick={handleSignIn} disabled={signingIn}>
		<LogIn />
		<span class="hidden sm:inline">Sign in</span>
	</Button>
{/if}
