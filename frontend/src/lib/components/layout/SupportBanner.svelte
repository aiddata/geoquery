<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Heart, X } from '@lucide/svelte';

	let visible = $state(false);

	$effect(() => {
		visible = localStorage.getItem('geoquery-support-dismissed') !== 'true';
	});

	function dismiss() {
		visible = false;
		localStorage.setItem('geoquery-support-dismissed', 'true');
	}
</script>

{#if visible}
	<div class="fixed bottom-4 right-4 z-40 w-72 rounded-xl bg-card text-card-foreground shadow-card contrast-more:border" data-slot="floating-panel">
		<div class="p-4">
			<Button
				variant="ghost"
				size="icon-sm"
				onclick={dismiss}
				class="absolute right-1.5 top-1.5 text-muted-foreground"
				aria-label="Dismiss"
			>
				<X />
			</Button>

			<div class="flex items-start gap-3 pr-6">
				<Heart class="mt-0.5 size-4 shrink-0 text-foreground" aria-hidden="true" />
				<div>
					<p class="text-sm font-bold">GeoQuery is a free service.</p>
					<p class="mt-1 text-sm text-muted-foreground">
						Are you a funder or donor? Help us help others.
					</p>
					<Button size="sm" class="mt-3" href="mailto:awooley@aiddata.org?subject=Supporting GeoQuery">
						Contact our partnerships team
					</Button>
				</div>
			</div>
		</div>
	</div>
{/if}
