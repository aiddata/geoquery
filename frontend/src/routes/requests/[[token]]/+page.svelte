<script lang="ts">
    import { page } from "$app/state";
    import { goto } from "$app/navigation";
    import { Button } from "$lib/components/ui/button";
    import { ArrowLeft, Search, Mail } from "@lucide/svelte";
    import { requestHistoryLink, fetchRequestsByToken, type PastRequest } from "$lib/api";

    const token = $derived(page.params.token ?? "");

    let email = $state("");
    let inputEl: HTMLInputElement | undefined = $state();
    let isValidEmail = $derived((email, inputEl?.validity.valid ?? false));

    let requests = $state<PastRequest[]>([]);
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
            requests = await fetchRequestsByToken(t);
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

    $effect(() => {
        if (token) loadHistory(token);
    });
</script>

<div class="container mx-auto max-w-2xl px-4 py-8">
    <div class="mb-6">
        <Button variant="ghost" onclick={() => goto("/")}>
            <ArrowLeft class="mr-1 h-4 w-4" />
            Back to Map
        </Button>
    </div>

    <div class="rounded-lg border bg-card p-6 shadow-sm">

        {#if !token}
            <h1 class="mb-2 text-2xl font-semibold">Past Requests</h1>
            <p class="mb-6 text-muted-foreground">
                Enter your email and we'll send you a personal link to your request history.
            </p>

            {#if sent}
                <div class="flex items-start gap-3 rounded-md border border-green-200 bg-green-50 p-4 text-sm text-green-800">
                    <Mail class="mt-0.5 h-4 w-4 shrink-0" />
                    <span>Link sent! Check your inbox for an email with your request history link.</span>
                </div>
                <p class="mt-4 text-center text-sm text-muted-foreground">
                    Didn't receive it?
                    <button class="underline" onclick={() => { sent = false; }}>Try again</button>
                </p>
            {:else}
                <form
                    onsubmit={(e) => { e.preventDefault(); sendLink(); }}
                    class="space-y-4"
                >
                    <div class="flex gap-2">
                        <div class="relative flex-1">
                            <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                            <input
                                type="email"
                                bind:this={inputEl}
                                bind:value={email}
                                placeholder="your@email.com"
                                class="w-full rounded-md border bg-background py-2 pl-10 pr-4 text-sm outline-none focus:ring-2 focus:ring-ring"
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
            {/if}

        {:else if loading}
            <p class="text-center text-muted-foreground">Loading your requests…</p>

        {:else if expired}
            <h1 class="mb-2 text-2xl font-semibold">Link Expired</h1>
            <p class="mb-6 text-muted-foreground">
                This link has expired. Request a new one below.
            </p>
            {#if sent}
                <div class="flex items-start gap-3 rounded-md border border-green-200 bg-green-50 p-4 text-sm text-green-800">
                    <Mail class="mt-0.5 h-4 w-4 shrink-0" />
                    <span>Link sent! Check your inbox.</span>
                </div>
            {:else}
                <form
                    onsubmit={(e) => { e.preventDefault(); sendLink(); }}
                    class="space-y-4"
                >
                    <div class="flex gap-2">
                        <div class="relative flex-1">
                            <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                            <input
                                type="email"
                                bind:this={inputEl}
                                bind:value={email}
                                placeholder="your@email.com"
                                class="w-full rounded-md border bg-background py-2 pl-10 pr-4 text-sm outline-none focus:ring-2 focus:ring-ring"
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
            <h1 class="mb-2 text-2xl font-semibold">Invalid Link</h1>
            <p class="text-muted-foreground">{error}</p>
            <div class="mt-4">
                <Button variant="outline" onclick={() => goto("/requests")}>Request a new link</Button>
            </div>

        {:else}
            <h1 class="mb-2 text-2xl font-semibold">Your Requests</h1>
            <p class="mb-6 text-muted-foreground">
                {requests.length} request{requests.length === 1 ? "" : "s"} found.
            </p>

            {#if requests.length === 0}
                <p class="text-center text-muted-foreground">No requests found for this account.</p>
            {:else}
                <div class="space-y-3">
                    {#each requests as request}
                        <button
                            class="block w-full rounded-md border p-4 text-left transition-colors hover:bg-muted/50"
                            onclick={() => goto(`/requests/${request.id}`)}
                        >
                            <div class="flex items-center justify-between">
                                <div class="font-medium">
                                    {request.name || "Unnamed Request"}
                                </div>
                                <span
                                    class="rounded-full px-2 py-0.5 text-xs font-medium
                                    {request.status_label === 'completed'
                                        ? 'bg-green-100 text-green-800'
                                        : request.status_label === 'processing' || request.status_label === 'preparing'
                                          ? 'bg-yellow-100 text-yellow-800'
                                          : request.status_label === 'error'
                                            ? 'bg-red-100 text-red-800'
                                            : 'bg-gray-100 text-gray-800'}"
                                >
                                    {request.status_label}
                                </span>
                            </div>
                            <div class="mt-1 text-sm text-muted-foreground">
                                {new Date(request.submit_time).toLocaleDateString()}
                            </div>
                        </button>
                    {/each}
                </div>
            {/if}
        {/if}

    </div>
</div>
