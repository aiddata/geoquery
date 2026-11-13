<script lang="ts">
	import { onMount } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { MonitorSmartphone, X } from '@lucide/svelte';
	import { MIN_LAYOUT_WIDTH, NOTICE_DISMISSED_KEY } from '#lib/smallScreen.js';

	// 'device': a phone or small tablet, shown a zoomed-out layout (app.html).
	// 'window': a desktop window narrower than the layout, which scrolls sideways.
	let reason = $state<'device' | 'window' | null>(null);
	let dismissed = $state(true);

	function check() {
		if (document.documentElement.hasAttribute('data-narrow-device')) reason = 'device';
		else reason = window.innerWidth < MIN_LAYOUT_WIDTH ? 'window' : null;
	}

	onMount(() => {
		try {
			dismissed = localStorage.getItem(NOTICE_DISMISSED_KEY) === 'true';
		} catch {
			dismissed = false;
		}
		check();
		window.addEventListener('resize', check);
		return () => window.removeEventListener('resize', check);
	});

	function dismiss() {
		dismissed = true;
		try {
			localStorage.setItem(NOTICE_DISMISSED_KEY, 'true');
		} catch {
			// Nothing to remember it in; it shows again next visit.
		}
	}
</script>

{#if reason && !dismissed}
	<!-- Text is scaled by --device-scale so it stays readable when a phone
	     shows the 1024px layout zoomed out. -->
	<div
		class="flex items-start gap-3 bg-band px-4 py-3 text-foreground"
		style="font-size: calc(0.875rem * var(--device-scale, 1))"
		role="status"
	>
		<MonitorSmartphone class="mt-0.5 shrink-0" style="width: 1.25em; height: 1.25em" aria-hidden="true" />
		<p class="min-w-0 flex-1">
			<strong>GeoQuery is designed for larger screens.</strong>
			{#if reason === 'device'}
				On this device pages are zoomed out to fit; pinch to zoom in. For the best experience,
				use a tablet or computer.
			{:else}
				Widen this window to at least {MIN_LAYOUT_WIDTH.toLocaleString()} pixels for the best
				layout; until then, pages scroll sideways.
			{/if}
		</p>
		<Button
			variant="ghost"
			size="icon-sm"
			class="shrink-0 text-muted-foreground"
			style="width: calc(2.75rem * var(--device-scale, 1)); height: calc(2.75rem * var(--device-scale, 1))"
			onclick={dismiss}
			aria-label="Dismiss"
		>
			<X style="width: calc(1.25rem * var(--device-scale, 1)); height: calc(1.25rem * var(--device-scale, 1))" />
		</Button>
	</div>
{/if}
