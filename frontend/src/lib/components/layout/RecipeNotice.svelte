<script lang="ts">
	import * as Alert from '#lib/components/ui/alert/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { recipeNotice } from '#lib/loadRecipe.js';
	import { History, TriangleAlert, X } from '@lucide/svelte';

	// After a request is loaded from a template (GEO-126): where it came from,
	// and anything left out because it no longer applies. Stays until dismissed.
</script>

{#if $recipeNotice}
	{@const notice = $recipeNotice}
	<div class="px-4 pt-3">
		<Alert.Root variant={notice.dropped.length ? 'warning' : 'default'} role="status" class="relative pr-10">
			{#if notice.dropped.length}<TriangleAlert />{:else}<History />{/if}
			<Alert.Title>{notice.title}</Alert.Title>
			<Alert.Description>
				{#if notice.dropped.length}
					<p>Some of it couldn’t be loaded:</p>
					<ul class="mt-1 list-disc space-y-0.5 pl-4">
						{#each notice.dropped as line}
							<li>{line}</li>
						{/each}
					</ul>
				{:else}
					<p>Its boundaries and datasets are loaded. Change anything before you submit.</p>
				{/if}
			</Alert.Description>
			<Button
				variant="ghost"
				size="icon-sm"
				class="absolute right-1.5 top-1.5 text-muted-foreground"
				aria-label="Dismiss"
				onclick={() => recipeNotice.set(null)}
			>
				<X />
			</Button>
		</Alert.Root>
	</div>
{/if}
