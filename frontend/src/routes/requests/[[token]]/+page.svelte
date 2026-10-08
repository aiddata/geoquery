<script lang="ts">
    import { page } from "$app/state";
    import { goto } from "$app/navigation";
    import { Button } from "$lib/components/ui/button";
    import { Input } from "$lib/components/ui/input";
    import * as Alert from "$lib/components/ui/alert";
    import * as Collapsible from "$lib/components/ui/collapsible";
    import StatusBadge, { requestStatusMeaning } from "$lib/components/StatusBadge.svelte";
    import { ArrowLeft, Search, Mail, BarChart2, LogIn, Archive, ChevronDown } from "@lucide/svelte";
    import {
        requestHistoryLink,
        fetchRequestsByToken,
        fetchMyRequests,
        fetchLegacyRequestsByToken,
        fetchMyLegacyRequests,
        type PastRequest,
        type LegacyPastRequest
    } from "$lib/api";
    import { auth } from "$lib/stores/auth";
    import { loginWithGitHub } from "$lib/allauth";

    const token = $derived(page.params.token ?? "");

    let email = $state("");
    let isValidEmail = $derived(/^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test(email));

    let requests = $state<PastRequest[]>([]);
    let legacyRequests = $state<LegacyPastRequest[]>([]);
    let loading = $state(false);
    let sending = $state(false);
    let sent = $state(false);
    let error = $state("");
    let expired = $state(false);

    async function sendLink() {
        if (!isValidEmail) return;
        sending = true;
        error = "";
        try {
            await requestHistoryLink(email);
            sent = true;
        } catch (e: any) {
            error = e.message || "Failed to send link. Please try again.";
        } finally {
            sending = false;
        }
    }

    async function loadHistory(t: string) {
        loading = true;
        error = "";
        expired = false;
        try {
            const [current, legacy] = await Promise.all([
                fetchRequestsByToken(t),
                fetchLegacyRequestsByToken(t).catch(() => [])
            ]);
            requests = current;
            legacyRequests = legacy;
        } catch (e: any) {
            if (e.message === "expired") {
                expired = true;
            } else {
                error = "This link is invalid or has expired.";
            }
        } finally {
            loading = false;
        }
    }

    // Signed-in users see their linked requests directly — no magic link needed.
    let showingMine = $state(false);
    async function loadMine() {
        loading = true;
        error = "";
        try {
            const [current, legacy] = await Promise.all([
                fetchMyRequests(),
                fetchMyLegacyRequests().catch(() => [])
            ]);
            requests = current;
            legacyRequests = legacy;
            showingMine = true;
        } catch {
            error = "Failed to load your requests. Please try again.";
        } finally {
            loading = false;
        }
    }

    $effect(() => {
        if (token) loadHistory(token);
        else if ($auth.status === "authenticated") loadMine();
    });
</script>

<div class="container mx-auto max-w-2xl px-4 py-8">
    <div class="mb-6">
        <Button variant="ghost" onclick={() => goto("/")}>
            <ArrowLeft />
            Back to Map
        </Button>
    </div>

    <div class="card-surface p-6">

        {#if loading || (!token && $auth.status === "loading")}
            <p class="text-center text-muted-foreground">Loading your requests…</p>

        {:else if !token && !showingMine}
            <h1 class="mb-2 text-h2">Past Requests</h1>
            <p class="mb-6 text-muted-foreground">
                Enter your email and we'll send you a personal link to your request history.
            </p>

            {#if sent}
                <Alert.Root variant="success" role="status">
                    <Mail />
                    <Alert.Description>Link sent! Check your inbox for an email with your request history link.</Alert.Description>
                </Alert.Root>
                <p class="mt-4 text-center text-sm text-muted-foreground">
                    Didn't receive it?
                    <Button variant="link" class="h-auto min-h-0 p-0 align-baseline font-body text-sm font-normal underline" onclick={() => { sent = false; }}>Try again</Button>
                </p>
            {:else}
                <form
                    onsubmit={(e) => { e.preventDefault(); sendLink(); }}
                    class="space-y-4"
                >
                    <div class="flex gap-2">
                        <div class="relative flex-1">
                            <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                            <Input
                                type="email"
                                bind:value={email}
                                placeholder="your@email.com"
                                aria-label="Email address"
                                class="pl-10"
                                required
                            />
                        </div>
                        <Button type="submit" disabled={!isValidEmail || sending}>
                            {sending ? "Sending..." : "Send Link"}
                        </Button>
                    </div>
                </form>

                {#if error}
                    <p class="mt-4 text-sm text-destructive">{error}</p>
                {/if}

                <div class="mt-6 border-t pt-4 text-center text-sm text-muted-foreground">
                    Or
                    <Button variant="link" class="h-auto min-h-0 gap-1 p-0 align-baseline font-body text-sm font-normal underline" onclick={() => loginWithGitHub("/requests")}>
                        <LogIn />
                        sign in with GitHub
                    </Button>
                    to see your requests automatically.
                </div>
            {/if}

        {:else if expired}
            <h1 class="mb-2 text-h2">Link Expired</h1>
            <p class="mb-6 text-muted-foreground">
                This link has expired. Request a new one below.
            </p>
            {#if sent}
                <Alert.Root variant="success" role="status">
                    <Mail />
                    <Alert.Description>Link sent! Check your inbox.</Alert.Description>
                </Alert.Root>
            {:else}
                <form
                    onsubmit={(e) => { e.preventDefault(); sendLink(); }}
                    class="space-y-4"
                >
                    <div class="flex gap-2">
                        <div class="relative flex-1">
                            <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                            <Input
                                type="email"
                                bind:value={email}
                                placeholder="your@email.com"
                                aria-label="Email address"
                                class="pl-10"
                                required
                            />
                        </div>
                        <Button type="submit" disabled={!isValidEmail || sending}>
                            {sending ? "Sending..." : "Send New Link"}
                        </Button>
                    </div>
                </form>
                {#if error}
                    <p class="mt-4 text-sm text-destructive">{error}</p>
                {/if}
            {/if}

        {:else if error}
            <h1 class="mb-2 text-h2">Invalid Link</h1>
            <p class="text-muted-foreground">{error}</p>
            <div class="mt-4">
                <Button variant="outline" onclick={() => goto("/requests")}>Request a new link</Button>
            </div>

        {:else}
            <h1 class="mb-2 text-h2">Your Requests</h1>
            <p class="mb-6 text-muted-foreground">
                {requests.length} request{requests.length === 1 ? "" : "s"} found{legacyRequests.length
                    ? `, plus ${legacyRequests.length} archived`
                    : ""}.
                {#if showingMine}
                    Missing older requests? <a href="/account" class="text-link underline hover:text-link-hover">Verify another
                    email address</a> to link them to your account.
                {/if}
            </p>

            {#if requests.length === 0 && legacyRequests.length === 0}
                <p class="text-center text-muted-foreground">No requests found for this account.</p>
            {:else}
                <div class="space-y-3">
                    {#each requests as request}
                        <a
                            href="/requests/{request.id}"
                            class="block w-full rounded-md border p-4 text-left transition-colors hover:bg-muted"
                        >
                            <div class="flex items-center justify-between gap-2">
                                <div class="font-bold">
                                    {request.name || "Unnamed Request"}
                                </div>
                                <StatusBadge meaning={requestStatusMeaning(request.status)}>
                                    {request.status_label}
                                </StatusBadge>
                            </div>
                            <div class="mt-1 text-sm text-muted-foreground">
                                {new Date(request.submit_time).toLocaleDateString()}
                            </div>
                        </a>
                    {/each}
                </div>
            {#if legacyRequests.length > 0}
                <Collapsible.Root class="mt-6 border-t pt-4">
                    <Collapsible.Trigger
                        class="group flex w-full items-center justify-between rounded-md px-1 py-2 text-left hover:bg-muted/50"
                    >
                        <span class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                            <Archive class="h-4 w-4" />
                            Archived requests (2016–2026)
                            <span class="rounded-full bg-muted px-2 py-0.5 text-xs">
                                {legacyRequests.length}
                            </span>
                        </span>
                        <ChevronDown
                            class="h-4 w-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180"
                        />
                    </Collapsible.Trigger>
                    <Collapsible.Content>
                        <p class="px-1 py-2 text-xs text-muted-foreground">
                            Requests from the previous version of GeoQuery. Results remain
                            downloadable, but these cannot be re-run or visualized.
                        </p>
                        <div class="space-y-3">
                            {#each legacyRequests as request}
                                <button
                                    class="block w-full rounded-md border border-dashed bg-muted/20 p-4 text-left transition-colors hover:bg-muted/50"
                                    onclick={() => goto(`/requests/legacy/${request.id}`)}
                                >
                                    <div class="flex items-center justify-between gap-2">
                                        <div class="font-medium text-muted-foreground">
                                            {request.name || "Unnamed Request"}
                                        </div>
                                        <span
                                            class="flex shrink-0 items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
                                        >
                                            <Archive class="h-3 w-3" />
                                            archived
                                        </span>
                                    </div>
                                    <div class="mt-1 text-sm text-muted-foreground">
                                        {new Date(request.submit_time).toLocaleDateString()}
                                        · {request.dataset_count} dataset{request.dataset_count === 1
                                            ? ""
                                            : "s"}
                                    </div>
                                </button>
                            {/each}
                        </div>
                    </Collapsible.Content>
                </Collapsible.Root>
            {/if}
            {/if}
        {/if}

    </div>

    <a
        href="/stats"
        class="card-surface mt-4 flex items-center gap-3 px-5 py-3 transition-colors hover:bg-muted"
    >
        <BarChart2 class="h-5 w-5 shrink-0 text-muted-foreground" />
        <div class="flex-1">
            <p class="text-sm font-bold">System Status</p>
            <p class="text-sm text-muted-foreground">View processing queue and system stats</p>
        </div>
        <ArrowLeft class="h-4 w-4 rotate-180 text-muted-foreground" />
    </a>
</div>
