<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
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
		<p class="text-center text-sm text-muted-foreground">Your Request is Empty</p>
	{:else}
		<Separator />
		<div class="space-y-2">
			{#each $cart as item, i}
				<Collapsible.Root>
					<div class="flex items-center gap-2 rounded-md bg-muted p-2">
						<Collapsible.Trigger>
							{#snippet child({ props })}
								<Button {...props} variant="ghost" size="icon-sm" aria-label="Show details">
									<ChevronRight class="transition-transform [[data-state=open]_&]:rotate-90" />
								</Button>
							{/snippet}
						</Collapsible.Trigger>
						<label for="cart-item-name-{i}" class="sr-only">Selection name</label>
						<Input
							id="cart-item-name-{i}"
							type="text"
							value={item.customName}
							oninput={(e) => cart.updateItemName(i, (e.target as HTMLInputElement).value)}
							placeholder="Selection Name"
							class="flex-1"
						/>
						<Button
							variant="ghost"
							size="icon-sm"
							onclick={() => cart.removeItem(i)}
							aria-label="Remove {item.customName || item.datasetTitle}"
						>
							<MinusCircle />
						</Button>
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
