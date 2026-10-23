<script lang="ts">
	import { banner } from '$lib/config/status';
	import { Button } from '$lib/components/ui/button';
	import { X, Info, AlertTriangle, AlertCircle } from '@lucide/svelte';

	let dismissed = $state(false);

	const icons = { info: Info, warning: AlertTriangle, error: AlertCircle };
	// design-system.md §11 site-wide banner
	const styles = {
		info: 'bg-forest text-cream',
		warning: 'bg-gold text-forest',
		error: 'bg-danger text-white',
	};

	const Icon = $derived(icons[banner.type]);
	const style = $derived(styles[banner.type]);
</script>

{#if banner.enabled && !dismissed}
	<div class="relative z-50 flex items-center justify-center gap-2 px-4 py-2 text-sm {style}">
		<Icon class="h-4 w-4 shrink-0" />
		<span>{banner.message}</span>
		<Button
			variant="ghost"
			size="icon-sm"
			onclick={() => (dismissed = true)}
			class="absolute right-2 text-current hover:bg-current/10 hover:text-current focus-visible:outline-current"
			aria-label="Dismiss"
		>
			<X />
		</Button>
	</div>
{/if}