<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Plus, Minus } from '@lucide/svelte';

	interface Props {
		onZoomIn?: () => void;
		onZoomOut?: () => void;
	}

	let { onZoomIn, onZoomOut }: Props = $props();
</script>

<div class="card-surface flex flex-col gap-1">
	<Button variant="ghost" size="icon" onclick={onZoomIn} aria-label="Zoom in">
		<Plus />
	</Button>
	<Button variant="ghost" size="icon" onclick={onZoomOut} aria-label="Zoom out">
		<Minus />
	</Button>
</div>
