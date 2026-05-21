<script lang="ts">
    import { goto } from "$app/navigation";
    import { Button } from "$lib/components/ui/button";
    import { Separator } from "$lib/components/ui/separator";
    import { ArrowLeft, Search } from "@lucide/svelte";
    import { fetchRequestsByEmail, type PastRequest } from "$lib/api";

    let email = $state("");
    let inputEl: HTMLInputElement | undefined = $state();
    // Read `email` to make Svelte re-run this whenever the value changes,
    // then check the DOM element's built-in validity.
    let isValidEmail = $derived((email, inputEl?.validity.valid ?? false));
    let requests = $state<PastRequest[]>([]);
    let loading = $state(false);
    let searched = $state(false);
    let error = $state("");

    async function lookupRequests() {
        if (!isValidEmail) return;
        loading = true;
        error = "";

        try {
            requests = await fetchRequestsByEmail(email);
            searched = true;
        } catch (e) {
            error = "Failed to lookup requests. Please try again.";
        } finally {
            loading = false;
        }
    }
</script>

<div class="container mx-auto max-w-2xl px-4 py-8">
    <div class="mb-6">
        <Button variant="ghost" onclick={() => goto("/")}>
            <ArrowLeft class="mr-1 h-4 w-4" />
            Back to Map
        </Button>
    </div>

    <div class="rounded-lg border bg-card p-6 shadow-sm">
        <h1 class="mb-2 text-2xl font-semibold">Past Requests</h1>
        <p class="mb-6 text-muted-foreground">
            Enter your email address to view your previous data requests.
        </p>

        <form
            onsubmit={(e) => {
                e.preventDefault();
                lookupRequests();
            }}
            class="space-y-4"
        >
            <div class="flex gap-2">
                <div class="relative flex-1">
                    <Search
                        class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                    />
                    <input
                        type="email"
                        bind:this={inputEl}
                        bind:value={email}
                        placeholder="your@email.com"
                        class="w-full rounded-md border bg-background py-2 pl-10 pr-4 text-sm outline-none focus:ring-2 focus:ring-ring"
                        required
                    />
                </div>
                <Button type="submit" disabled={!isValidEmail || loading}>
                    {loading ? "Loading..." : "Lookup"}
                </Button>
            </div>
        </form>

        {#if error}
            <p class="mt-4 text-sm text-destructive">{error}</p>
        {/if}

        {#if searched}
            <Separator class="my-6" />

            {#if requests.length === 0}
                <p class="text-center text-muted-foreground">
                    No requests found for this email address.
                </p>
            {:else}
                <div class="space-y-3">
                    {#each requests as request}
                        <div class="block rounded-md border p-4">
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
                        </div>
                    {/each}
                </div>
            {/if}
        {/if}
    </div>
</div>
