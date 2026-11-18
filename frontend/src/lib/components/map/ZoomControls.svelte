<script lang="ts">
	import { Plus, Minus, Focus } from '@lucide/svelte';
	import MapToolButton from './MapToolButton.svelte';

	interface Props {
		onZoomIn?: () => void;
		onZoomOut?: () => void;
		/** Zoom to the selection's extent; the button is shown only when given */
		onZoomToSelection?: () => void;
		/** Nothing selected to zoom to */
		selectionEmpty?: boolean;
	}

	let { onZoomIn, onZoomOut, onZoomToSelection, selectionEmpty = false }: Props = $props();
</script>

<div class="card-surface flex flex-col gap-1">
	{#if onZoomToSelection}
		<MapToolButton
			label="Zoom to selected boundaries"
			tooltip={selectionEmpty ? 'Select boundaries to zoom to them' : undefined}
			disabled={selectionEmpty}
			onclick={onZoomToSelection}
		>
			<Focus />
		</MapToolButton>
	{/if}
	<MapToolButton label="Zoom in" onclick={onZoomIn}><Plus /></MapToolButton>
	<MapToolButton label="Zoom out" onclick={onZoomOut}><Minus /></MapToolButton>
</div>
