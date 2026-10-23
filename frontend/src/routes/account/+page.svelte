<script lang="ts">
    import { goto } from "$app/navigation";
    import { Badge } from "$lib/components/ui/badge";
    import * as Alert from "$lib/components/ui/alert";
    import { Button } from "$lib/components/ui/button";
    import { Input } from "$lib/components/ui/input";
    import { Separator } from "$lib/components/ui/separator";
    import { auth } from "$lib/stores/auth";
    import {
        addEmail,
        listEmails,
        listProviders,
        removeEmail,
        resendVerification,
        setPrimaryEmail,
        type EmailAddress,
        type ProviderAccount,
        loginWithGitHub
    } from "$lib/allauth";
    import { ArrowLeft, CircleAlert, CircleCheck, Clock, History, LogIn, Mail, Plus } from "@lucide/svelte";
    import { page } from "$app/state";
    import { DEFAULT_NEXT, navigateNext, readNext } from "$lib/utils/nextDestination";

    // Usually absent. Django's OIDC provider sets it when a chat client
    // connecting to the MCP server needs a session first: sign in, then go
    // back to /authorize and finish the handshake.
    const nextDestination = $derived(readNext(page.url));

    let emails = $state<EmailAddress[]>([]);
    let providers = $state<ProviderAccount[]>([]);
    let loading = $state(true);

    let newEmail = $state("");
    let isValidEmail = $derived(/^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test(newEmail));
    let busy = $state(false);
    let error = $state("");
    let notice = $state("");

    async function load() {
        loading = true;
        try {
            [emails, providers] = await Promise.all([listEmails(), listProviders()]);
        } catch (e: any) {
            error = e.message || "Failed to load account details.";
        } finally {
            loading = false;
        }
    }

    $effect(() => {
        if ($auth.status !== "authenticated") return;
        // Already signed in and only passing through: don't make them look at
        // an account page they didn't ask for.
        if (nextDestination !== DEFAULT_NEXT) {
            navigateNext(nextDestination);
            return;
        }
        load();
    });

    async function run(action: () => Promise<unknown>, successMessage: string) {
        busy = true;
        error = "";
        notice = "";
        try {
            await action();
            notice = successMessage;
            emails = await listEmails();
        } catch (e: any) {
            error = e.message || "Something went wrong. Please try again.";
        } finally {
            busy = false;
        }
    }

    function handleAddEmail() {
        if (!isValidEmail) return;
        const email = newEmail.trim();
        run(async () => {
            await addEmail(email);
            newEmail = "";
        }, `Verification email sent to ${email}. Verifying it will also link any past requests submitted under that address.`);
    }
</script>

<div class="container mx-auto max-w-2xl px-4 py-8">
    <div class="mb-6">
        <Button variant="ghost" onclick={() => goto("/")}>
            <ArrowLeft />
            Back to Map
        </Button>
    </div>

    {#if $auth.status === "loading"}
        <div class="card-surface p-6">
            <p class="text-center text-muted-foreground">Loading…</p>
        </div>
    {:else if $auth.status === "anonymous"}
        <div class="card-surface p-6 text-center">
            <h1 class="mb-2 text-h2">Account</h1>
            <p class="mb-6 text-muted-foreground">Sign in to manage your account and past requests.</p>
            <Button onclick={() => loginWithGitHub(nextDestination)}>
                <LogIn />
                Sign in with GitHub
            </Button>
        </div>
    {:else}
        <div class="card-surface p-6">
            <h1 class="mb-6 text-h2">Account</h1>

            {#if providers.length > 0}
                <div class="mb-6 flex flex-wrap items-center gap-2">
                    {#each providers as account}
                        <Badge variant="secondary" class="gap-1.5 py-1">
                            {account.provider.name}: {account.display}
                        </Badge>
                    {/each}
                </div>
            {/if}

            <Separator class="mb-6" />

            <h2 class="mb-1 text-h4">Email addresses</h2>
            <p class="mb-4 text-sm text-muted-foreground">
                Used GeoQuery before? Add and verify an email address you submitted requests
                with, and those requests will be linked to your account automatically.
            </p>

            {#if loading}
                <p class="text-muted-foreground">Loading…</p>
            {:else}
                <div class="space-y-2">
                    {#each emails as item (item.email)}
                        <div class="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3">
                            <div class="flex min-w-0 items-center gap-2">
                                <Mail class="h-4 w-4 shrink-0 text-muted-foreground" />
                                <span class="truncate text-sm font-bold">{item.email}</span>
                                {#if item.primary}
                                    <Badge>primary</Badge>
                                {/if}
                                {#if item.verified}
                                    <Badge variant="success"><CircleCheck aria-hidden="true" />verified</Badge>
                                {:else}
                                    <Badge variant="warning"><Clock aria-hidden="true" />unverified</Badge>
                                {/if}
                            </div>
                            <div class="flex shrink-0 gap-1">
                                {#if !item.verified}
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        disabled={busy}
                                        onclick={() => run(() => resendVerification(item.email), `Verification email re-sent to ${item.email}.`)}
                                    >
                                        Resend
                                    </Button>
                                {/if}
                                {#if item.verified && !item.primary}
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        disabled={busy}
                                        onclick={() => run(() => setPrimaryEmail(item.email), `${item.email} is now your primary address.`)}
                                    >
                                        Make primary
                                    </Button>
                                {/if}
                                {#if !item.primary}
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        class="text-destructive hover:text-destructive"
                                        disabled={busy}
                                        onclick={() => run(() => removeEmail(item.email), `${item.email} removed.`)}
                                    >
                                        Remove
                                    </Button>
                                {/if}
                            </div>
                        </div>
                    {/each}
                </div>

                <form
                    class="mt-4 flex gap-2"
                    onsubmit={(e) => {
                        e.preventDefault();
                        handleAddEmail();
                    }}
                >
                    <Input
                        type="email"
                        bind:value={newEmail}
                        placeholder="another@email.com"
                        aria-label="Email address to add"
                        class="flex-1"
                    />
                    <Button type="submit" disabled={!isValidEmail || busy}>
                        <Plus />
                        Add email
                    </Button>
                </form>

                {#if notice}
                    <Alert.Root variant="success" role="status" class="mt-4">
                        <CircleCheck />
                        <Alert.Description>{notice}</Alert.Description>
                    </Alert.Root>
                {/if}
                {#if error}
                    <Alert.Root variant="destructive" class="mt-4">
                        <CircleAlert />
                        <Alert.Description>{error}</Alert.Description>
                    </Alert.Root>
                {/if}
            {/if}
        </div>

        <a
            href="/requests"
            class="card-surface mt-4 flex items-center gap-3 px-5 py-3 transition-colors hover:bg-muted/50"
        >
            <History class="h-5 w-5 shrink-0 text-muted-foreground" />
            <div class="flex-1">
                <p class="text-sm font-bold">My Requests</p>
                <p class="text-sm text-muted-foreground">View requests linked to your account</p>
            </div>
            <ArrowLeft class="h-4 w-4 rotate-180 text-muted-foreground" />
        </a>
    {/if}
</div>
