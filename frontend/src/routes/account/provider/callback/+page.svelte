<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { refreshAuth, setAuthSession } from '$lib/stores/auth';
	import {
		AllauthRequestError,
		describeAuthError,
		getProviderSignup,
		loginWithGitHub,
		submitProviderSignup,
		type AuthSession
	} from '$lib/allauth';
	import { LoaderCircle, MailCheck, TriangleAlert } from '@lucide/svelte';

	type CallbackView = 'loading' | 'provider-signup' | 'verify-email' | 'error';
	type ErrorAction = 'none' | 'check' | 'restart';

	const RETRYABLE_OAUTH_ERRORS = [
		'unknown',
		'cancelled',
		'denied',
		'invalid_token',
		'no_verified_email'
	];

	let view = $state<CallbackView>('loading');
	let error = $state('');
	let errorCode = $state<string | null>(null);
	let errorAction = $state<ErrorAction>('none');
	let connecting = $state(false);
	let signupEmail = $state('');
	let signupError = $state('');
	let submitting = $state(false);

	const nextDestination = $derived(page.url.searchParams.get('next') ?? '/account');
	const normalizedEmail = $derived(signupEmail.trim());
	const emailIsValid = $derived(/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail));

	function showError(
		message: string,
		action: ErrorAction = 'none',
		code: string | null = null
	) {
		error = message;
		errorCode = code;
		errorAction = action;
		view = 'error';
	}

	function showServiceError(cause: unknown) {
		const message =
			cause instanceof AllauthRequestError && cause.status < 500
				? cause.message
				: 'GeoQuery could not reach the sign-in service. Check your connection and try again.';
		showError(message, 'check');
	}

	async function loadProviderSignup() {
		try {
			const details = await getProviderSignup();
			const suggestedEmail =
				details.email.find((item) => item.primary)?.email ??
				details.email[0]?.email ??
				details.user.email ??
				'';
			if (!signupEmail) signupEmail = suggestedEmail;
			signupError = '';
			view = 'provider-signup';
		} catch (cause) {
			if (cause instanceof AllauthRequestError && cause.status === 409) {
				showError(
					'This GitHub sign-in setup has expired. Start the sign-in process again.',
					'restart'
				);
				return;
			}
			if (cause instanceof AllauthRequestError && cause.status === 403) {
				showError(describeAuthError('signup_closed', null), 'none', 'signup_closed');
				return;
			}
			throw cause;
		}
	}

	async function handleSession(session: AuthSession) {
		setAuthSession(session);
		if (session.status === 'authenticated') {
			await goto(nextDestination, { replaceState: true });
			return;
		}

		switch (session.pendingFlow) {
			case 'provider_signup':
				await loadProviderSignup();
				return;
			case 'verify_email':
				view = 'verify-email';
				return;
			case null:
				showError(
					describeAuthError(null, connecting ? 'connect' : null),
					connecting ? 'none' : 'restart'
				);
				return;
			default:
				showError(
					`GitHub authorized the request, but the remaining “${session.pendingFlow}” sign-in step is not available on this page. Start again or contact an administrator.`,
					'restart',
					session.pendingFlow
				);
		}
	}

	async function loadCallback() {
		view = 'loading';
		error = '';
		errorCode = null;
		errorAction = 'none';
		signupError = '';

		const errorParam = page.url.searchParams.get('error');
		const processParam = page.url.searchParams.get('error_process');
		connecting = processParam === 'connect';
		if (errorParam) {
			const retryable =
				!connecting && RETRYABLE_OAUTH_ERRORS.includes(errorParam);
			showError(
				describeAuthError(errorParam, processParam),
				retryable ? 'restart' : 'none',
				errorParam
			);
			return;
		}

		try {
			await handleSession(await refreshAuth());
		} catch (cause) {
			showServiceError(cause);
		}
	}

	async function restartLogin() {
		view = 'loading';
		try {
			await loginWithGitHub(nextDestination);
		} catch (cause) {
			showServiceError(cause);
		}
	}

	async function handleProviderSubmit() {
		if (!emailIsValid || submitting) return;
		submitting = true;
		signupError = '';

		try {
			await handleSession(await submitProviderSignup(normalizedEmail));
		} catch (cause) {
			if (cause instanceof AllauthRequestError && cause.status === 409) {
				// The POST may have completed even if its response was lost.
				// Re-read the session before declaring the pending signup expired.
				try {
					const session = await refreshAuth();
					if (session.status === 'anonymous' && session.pendingFlow === null) {
						showError(
							'This GitHub sign-in setup has expired. Start the sign-in process again.',
							'restart'
						);
					} else {
						await handleSession(session);
					}
				} catch (recoveryCause) {
					showServiceError(recoveryCause);
				}
			} else if (cause instanceof AllauthRequestError && cause.status === 403) {
				showError(describeAuthError('signup_closed', null), 'none', 'signup_closed');
			} else if (cause instanceof AllauthRequestError && cause.status === 400) {
				signupError =
					cause.errors.find((item) => item.param === 'email')?.message ??
					cause.message;
			} else {
				signupError =
					'GeoQuery could not finish setting up your account. Your email was kept; please try again.';
			}
		} finally {
			submitting = false;
		}
	}

	onMount(() => {
		void loadCallback();
	});
</script>

<div class="mx-auto flex max-w-md flex-col items-center px-4 py-16">
	{#if view === 'provider-signup'}
		<form
			class="w-full"
			onsubmit={(event) => {
				event.preventDefault();
				void handleProviderSubmit();
			}}
		>
			<Card.Root>
				<Card.Header>
					<Card.Title>Finish setting up your account</Card.Title>
					<Card.Description>
						GitHub needs an email address to finish creating your GeoQuery account.
					</Card.Description>
				</Card.Header>
				<Card.Content class="space-y-2">
					<Label for="provider-signup-email">Email address</Label>
					<Input
						id="provider-signup-email"
						type="email"
						autocomplete="email"
						required
						bind:value={signupEmail}
						aria-invalid={Boolean(signupError)}
						aria-describedby={signupError ? 'provider-signup-error' : undefined}
					/>
					{#if signupError}
						<p id="provider-signup-error" class="text-sm text-destructive">{signupError}</p>
					{/if}
				</Card.Content>
				<Card.Footer class="flex-wrap gap-2">
					<Button type="submit" disabled={!emailIsValid || submitting}>
						{#if submitting}
							<LoaderCircle class="mr-1 h-4 w-4 animate-spin" />
						{/if}
						Continue
					</Button>
					<Button type="button" variant="outline" href="/">Cancel</Button>
				</Card.Footer>
			</Card.Root>
		</form>
	{:else if view === 'verify-email'}
		<Card.Root class="w-full">
			<Card.Header>
				<Card.Title class="flex items-center gap-2">
					<MailCheck class="h-5 w-5 text-muted-foreground" />
					Check your email
				</Card.Title>
				<Card.Description>
					To finish signing in, open the confirmation link GeoQuery sent to your email address.
				</Card.Description>
			</Card.Header>
			<Card.Footer class="flex-wrap gap-2">
				<Button onclick={() => void loadCallback()}>I've verified my email</Button>
				<Button variant="outline" href="/account">Go to account</Button>
				<Button variant="outline" href="/">Back to GeoQuery</Button>
			</Card.Footer>
		</Card.Root>
	{:else if view === 'error'}
		<Card.Root class="w-full">
			<Card.Header>
				<Card.Title class="flex items-center gap-2">
					<TriangleAlert class="h-5 w-5 text-destructive" />
					{connecting ? "Couldn't connect GitHub" : 'Sign-in failed'}
				</Card.Title>
				<Card.Description>{error}</Card.Description>
			</Card.Header>
			{#if errorCode}
				<Card.Content>
					<p class="text-xs text-muted-foreground">Error code: <code>{errorCode}</code></p>
				</Card.Content>
			{/if}
			<Card.Footer class="flex-wrap gap-2">
				{#if errorAction === 'check'}
					<Button onclick={() => void loadCallback()}>Check again</Button>
				{:else if errorAction === 'restart'}
					<Button onclick={() => void restartLogin()}>Try GitHub again</Button>
				{/if}
				<Button variant={errorAction === 'none' ? 'default' : 'outline'} href="/account">
					Go to account
				</Button>
				<Button variant="outline" href="/">Back to GeoQuery</Button>
			</Card.Footer>
		</Card.Root>
	{:else}
		<LoaderCircle class="h-8 w-8 animate-spin text-muted-foreground" />
		<p class="mt-4 text-sm text-muted-foreground">Completing sign-in…</p>
	{/if}
</div>
