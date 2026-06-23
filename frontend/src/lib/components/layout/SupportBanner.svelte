<script lang="ts">
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
	<div class="fixed bottom-4 right-4 z-40 w-72 rounded-lg border bg-background shadow-lg">
		<div class="p-4">
			<button
				onclick={dismiss}
				class="absolute right-2 top-2 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
				aria-label="Dismiss"
			>
				<X class="h-3.5 w-3.5" />
			</button>

			<div class="flex items-start gap-3 pr-4">
				<Heart class="mt-0.5 h-4 w-4 shrink-0 text-rose-500" />
				<div>
					<p class="text-sm font-medium leading-snug">GeoQuery is a free service.</p>
					<p class="mt-1 text-xs text-muted-foreground leading-snug">
						Are you a funder or donor? Help us help others.
					</p>
					<a
						href="mailto:awooley@aiddata.org?subject=Supporting GeoQuery"
						class="mt-3 inline-block rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
					>
						Contact our partnerships team
					</a>
				</div>
			</div>
		</div>
	</div>
{/if}
