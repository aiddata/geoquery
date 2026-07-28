<script lang="ts">
    import { onMount } from "svelte";
    import { page } from "$app/state";
    import { Button } from "$lib/components/ui/button";
    import { verifyEmail } from "$lib/allauth";
    import { CircleCheck, LoaderCircle, TriangleAlert } from "@lucide/svelte";

    let status = $state<"verifying" | "success" | "failure">("verifying");

    onMount(async () => {
        try {
            status = (await verifyEmail(page.params.key ?? "")) ? "success" : "failure";
        } catch {
            status = "failure";
        }
    });
</script>

<div class="container mx-auto max-w-2xl px-4 py-8">
    <div class="rounded-lg border bg-card p-6 text-center shadow-sm">
        {#if status === "verifying"}
            <LoaderCircle class="mx-auto h-8 w-8 animate-spin text-muted-foreground" />
            <p class="mt-4 text-muted-foreground">Verifying your email address…</p>
        {:else if status === "success"}
            <CircleCheck class="mx-auto h-8 w-8 text-green-600" />
            <h1 class="mt-4 text-2xl font-semibold">Email verified</h1>
            <p class="mt-2 text-muted-foreground">
                Any past GeoQuery requests submitted under this address are now linked to
                your account.
            </p>
            <div class="mt-6 flex justify-center gap-2">
                <Button href="/requests">View my requests</Button>
                <Button variant="outline" href="/account">Manage account</Button>
            </div>
        {:else}
            <TriangleAlert class="mx-auto h-8 w-8 text-destructive" />
            <h1 class="mt-4 text-2xl font-semibold">Verification failed</h1>
            <p class="mt-2 text-muted-foreground">
                This verification link is invalid or has expired. You can request a new one
                from your account page.
            </p>
            <div class="mt-6">
                <Button href="/account">Go to account</Button>
            </div>
        {/if}
    </div>
</div>
