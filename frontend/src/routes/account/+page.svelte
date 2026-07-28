<script lang="ts">
    import { goto } from "$app/navigation";
    import { Badge } from "$lib/components/ui/badge";
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
    import { ArrowLeft, History, LogIn, Mail, Plus } from "@lucide/svelte";

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
        if ($auth.status === "authenticated") load();
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
            <ArrowLeft class="mr-1 h-4 w-4" />
            Back to Map
        </Button>
    </div>

    {#if $auth.status === "loading"}
        <div class="rounded-lg border bg-card p-6 shadow-sm">
            <p class="text-center text-muted-foreground">Loading…</p>
        </div>
    {:else if $auth.status === "anonymous"}
        <div class="rounded-lg border bg-card p-6 shadow-sm text-center">
            <h1 class="mb-2 text-2xl font-semibold">Account</h1>
            <p class="mb-6 text-muted-foreground">Sign in to manage your account and past requests.</p>
            <Button onclick={() => loginWithGitHub("/account")}>
                <LogIn class="mr-1 h-4 w-4" />
                Sign in with GitHub
            </Button>
        </div>
    {:else}
        <div class="rounded-lg border bg-card p-6 shadow-sm">
            <h1 class="mb-1 text-2xl font-semibold">Account</h1>
            <p class="mb-6 text-muted-foreground">
                Signed in as {$auth.user.display || $auth.user.email}
            </p>

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

            <h2 class="mb-1 text-lg font-semibold">Email addresses</h2>
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
                                <span class="truncate text-sm font-medium">{item.email}</span>
                                {#if item.primary}
                                    <Badge>primary</Badge>
                                {/if}
                                {#if item.verified}
                                    <Badge variant="secondary" class="bg-green-100 text-green-800">verified</Badge>
                                {:else}
                                    <Badge variant="secondary" class="bg-yellow-100 text-yellow-800">unverified</Badge>
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
                        class="flex-1"
                    />
                    <Button type="submit" disabled={!isValidEmail || busy}>
                        <Plus class="mr-1 h-4 w-4" />
                        Add email
                    </Button>
                </form>

                {#if notice}
                    <p class="mt-4 text-sm text-green-700">{notice}</p>
                {/if}
                {#if error}
                    <p class="mt-4 text-sm text-destructive">{error}</p>
                {/if}
            {/if}
        </div>

        <a
            href="/requests"
            class="mt-4 flex items-center gap-3 rounded-lg border bg-card px-5 py-3 shadow-sm transition-colors hover:bg-muted/50"
        >
            <History class="h-5 w-5 shrink-0 text-muted-foreground" />
            <div class="flex-1">
                <p class="text-sm font-medium">My Requests</p>
                <p class="text-xs text-muted-foreground">View requests linked to your account</p>
            </div>
            <ArrowLeft class="h-4 w-4 rotate-180 text-muted-foreground" />
        </a>
    {/if}
</div>
