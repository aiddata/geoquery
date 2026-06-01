<script lang="ts">
	import { banner } from '$lib/config/status';
	import { X, Info, AlertTriangle, AlertCircle } from '@lucide/svelte';

	let dismissed = $state(false);

	const icons = { info: Info, warning: AlertTriangle, error: AlertCircle };
	const styles = {
		info: 'bg-blue-600 text-white',
		warning: 'bg-amber-500 text-white',
		error: 'bg-red-600 text-white',
	};

	const Icon = $derived(icons[banner.type]);
	const style = $derived(styles[banner.type]);
</script>

{#if banner.enabled && !dismissed}
	<div class="relative z-50 flex items-center justify-center gap-2 px-4 py-2 text-sm {style}">
		<Icon class="h-4 w-4 shrink-0" />
		<span>{banner.message}</span>
		<button
			onclick={() => (dismissed = true)}
			class="absolute right-3 rounded p-0.5 opacity-75 hover:opacity-100 focus:outline-none"
			aria-label="Dismiss"
		>
			<X class="h-4 w-4" />
		</button>
	</div>
{/if}