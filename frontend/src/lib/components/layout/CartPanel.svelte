<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Separator } from '$lib/components/ui/separator';
	import * as Collapsible from '$lib/components/ui/collapsible';
	import { ChevronRight, MinusCircle } from '@lucide/svelte';
	import { cart } from '$lib/stores/cart';
</script>

<div class="space-y-4 p-4">
	<Button class="w-full" disabled={$cart.length === 0} href="/review">
		Review Request
	</Button>

	{#if $cart.length === 0}
		<p class="text-center text-lg text-muted-foreground">Your Request is Empty</p>
	{:else}
		<Separator />
		<div class="space-y-2">
			{#each $cart as item, i}
				<Collapsible.Root>
					<div class="flex items-center gap-2 rounded-md bg-muted/50 p-2">
						<Collapsible.Trigger class="flex items-center">
							<ChevronRight class="h-4 w-4 transition-transform [[data-state=open]_&]:rotate-90" />
						</Collapsible.Trigger>
						<input
							type="text"
							value={item.customName}
							oninput={(e) => cart.updateItemName(i, (e.target as HTMLInputElement).value)}
							placeholder="Selection Name"
							class="flex-1 bg-transparent text-sm outline-none"
						/>
						<button onclick={() => cart.removeItem(i)} class="text-destructive hover:text-destructive/80">
							<MinusCircle class="h-5 w-5" />
						</button>
					</div>
					<Collapsible.Content class="px-6 py-2 text-sm text-muted-foreground">
						<p>Dataset: {item.datasetTitle}</p>
						<p class="mt-1 italic">{item.summary}</p>
					</Collapsible.Content>
				</Collapsible.Root>
			{/each}
		</div>
	{/if}
</div>
