<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Separator } from '$lib/components/ui/separator';
	import * as Collapsible from '$lib/components/ui/collapsible';
	import { ChevronRight, MinusCircle } from '@lucide/svelte';

	// TODO: Replace with actual cart store
	let cartItems: any[] = $state([]);

	function removeItem(index: number) {
		cartItems = cartItems.filter((_, i) => i !== index);
	}
</script>

<div class="space-y-4 p-4">
	<Button class="w-full" disabled={cartItems.length === 0} href="/checkout">
		Review Request
	</Button>

	{#if cartItems.length === 0}
		<p class="text-center text-lg text-muted-foreground">Your Request is Empty</p>
	{:else}
		<Separator />
		<div class="space-y-2">
			{#each cartItems as item, i}
				<Collapsible.Root>
					<div class="flex items-center gap-2 rounded-md bg-muted/50 p-2">
						<Collapsible.Trigger class="flex items-center">
							<ChevronRight class="h-4 w-4 transition-transform [[data-state=open]_&]:rotate-90" />
						</Collapsible.Trigger>
						<input
							type="text"
							bind:value={item.customName}
							placeholder="Request Name"
							class="flex-1 bg-transparent text-sm outline-none"
						/>
						<button onclick={() => removeItem(i)} class="text-destructive hover:text-destructive/80">
							<MinusCircle class="h-5 w-5" />
						</button>
					</div>
					<Collapsible.Content class="px-6 py-2 text-sm text-muted-foreground">
						<!-- Query details will go here -->
						<p>Dataset: {item.dataset || 'Unknown'}</p>
						<p>Boundary: {item.boundary || 'Unknown'}</p>
					</Collapsible.Content>
				</Collapsible.Root>
			{/each}
		</div>
	{/if}
</div>
