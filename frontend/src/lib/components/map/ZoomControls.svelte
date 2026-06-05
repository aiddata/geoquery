<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Plus, Minus } from '@lucide/svelte';

	interface Props {
		onZoomIn?: () => void;
		onZoomOut?: () => void;
	}

	let { onZoomIn, onZoomOut }: Props = $props();
</script>

<div class="flex flex-col gap-1 rounded-md border bg-background shadow-md">
	<Button variant="ghost" size="icon" onclick={onZoomIn} aria-label="Zoom in">
		<Plus class="h-4 w-4" />
	</Button>
	<Button variant="ghost" size="icon" onclick={onZoomOut} aria-label="Zoom out">
		<Minus class="h-4 w-4" />
	</Button>
</div>
