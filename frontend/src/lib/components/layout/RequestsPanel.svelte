<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Separator } from '$lib/components/ui/separator';

	let email = $state('');
	let requests: any[] = $state([]);
	let loading = $state(false);
	let searched = $state(false);

	async function lookupRequests() {
		if (!email) return;
		loading = true;
		// TODO: Implement actual API call
		// const response = await fetch('/api/requests', {
		//   method: 'POST',
		//   body: JSON.stringify({ email })
		// });
		// requests = await response.json();
		requests = [];
		searched = true;
		loading = false;
	}
</script>

<div class="space-y-4 p-4">
	<section>
		<p class="mb-4 text-sm text-muted-foreground">
			Enter your email address to view your past data requests.
		</p>

		<div class="flex gap-2">
			<input
				type="email"
				bind:value={email}
				placeholder="your@email.com"
				class="flex-1 rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
				onkeydown={(e) => e.key === 'Enter' && lookupRequests()}
			/>
			<Button onclick={lookupRequests} disabled={!email || loading}>
				{loading ? 'Loading...' : 'Lookup'}
			</Button>
		</div>
	</section>

	{#if searched}
		<Separator />

		{#if requests.length === 0}
			<p class="text-center text-muted-foreground">No requests found for this email.</p>
		{:else}
			<div class="space-y-2">
				{#each requests as request}
					<a
						href="/status/{request.id}"
						class="block rounded-md border p-3 transition-colors hover:bg-muted/50"
					>
						<div class="font-medium">{request.name || 'Unnamed Request'}</div>
						<div class="text-sm text-muted-foreground">
							{new Date(request.createdAt).toLocaleDateString()}
						</div>
						<div class="text-sm">
							Status:
							<span class="font-medium">{request.status}</span>
						</div>
					</a>
				{/each}
			</div>
		{/if}
	{/if}
</div>
