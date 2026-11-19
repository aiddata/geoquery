<script lang="ts">
	import { Upload } from '@lucide/svelte';

	// Lets a file be dropped anywhere on the page (GEO-137). While a file is
	// dragged over the window, the whole page dims under a drop target; the
	// drop hands the first file to `onFile`. Only files trigger it, not text
	// or links being dragged within the page.
	interface Props {
		onFile: (file: File) => void;
		/** What the drop does, shown on the overlay */
		label?: string;
		hint?: string;
	}

	let { onFile, label = 'Drop to upload', hint }: Props = $props();

	let active = $state(false);

	const hasFiles = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes('Files');

	function onWindowDragEnter(e: DragEvent) {
		if (hasFiles(e)) active = true;
	}

	// Without this the browser opens a file dropped outside the overlay
	function onWindowDragOver(e: DragEvent) {
		if (!hasFiles(e)) return;
		e.preventDefault();
		active = true;
	}

	function onWindowDrop(e: DragEvent) {
		if (hasFiles(e)) e.preventDefault();
		active = false;
	}

	function onOverlayDragOver(e: DragEvent) {
		e.preventDefault();
		if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
	}

	// Leaving the window (the drag goes to nothing on the page) clears it;
	// moving between elements within the page doesn't.
	function onOverlayDragLeave(e: DragEvent) {
		if (!e.relatedTarget) active = false;
	}

	function onOverlayDrop(e: DragEvent) {
		e.preventDefault();
		e.stopPropagation();
		active = false;
		const file = e.dataTransfer?.files?.[0];
		if (file) onFile(file);
	}

	function onKeydown(e: KeyboardEvent) {
		if (active && e.key === 'Escape') active = false;
	}
</script>

<svelte:window
	ondragenter={onWindowDragEnter}
	ondragover={onWindowDragOver}
	ondrop={onWindowDrop}
	onkeydown={onKeydown}
/>

{#if active}
	<!-- Drag and drop is pointer-only; keyboard and screen reader users have
	     the Custom upload button and its file picker, so this is hidden from
	     assistive technology -->
	<div
		class="fixed inset-0 z-[90] flex items-center justify-center bg-black/45 p-6 backdrop-blur-[1px] motion-safe:animate-in motion-safe:fade-in"
		aria-hidden="true"
		ondragover={onOverlayDragOver}
		ondragleave={onOverlayDragLeave}
		ondrop={onOverlayDrop}
	>
		<div class="pointer-events-none flex max-w-sm flex-col items-center gap-2 rounded-lg border-2 border-dashed border-primary bg-card px-8 py-6 text-center shadow-lg">
			<Upload class="size-8 text-primary" aria-hidden="true" />
			<p class="font-bold text-foreground">{label}</p>
			{#if hint}<p class="text-xs text-muted-foreground">{hint}</p>{/if}
		</div>
	</div>
{/if}
