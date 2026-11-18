<script lang="ts">
	import { ChevronDown } from '@lucide/svelte';

	// A pill pinned to the bottom of a scrolling options pane, naming the next
	// options section whose heading is out of view below (GEO-135). Clicking it
	// scrolls that section into view; it goes away once every section heading
	// has been seen. Place it as the last child of the scroll container.
	interface Props {
		/** The scroll container holding the options sections. */
		scroller: HTMLElement | undefined;
	}

	let { scroller }: Props = $props();

	let next = $state<{ heading: HTMLElement; title: string } | null>(null);

	// How much of a heading must show above the pane's bottom edge (and the
	// pill itself) to count as seen.
	const SEEN_MARGIN = 56;

	function update() {
		if (!scroller) {
			next = null;
			return;
		}
		const bottom = scroller.getBoundingClientRect().bottom - SEEN_MARGIN;
		const headings = scroller.querySelectorAll<HTMLElement>('section[aria-labelledby] h4');
		const hidden = [...headings].find((h) => h.getBoundingClientRect().top > bottom);
		// Only on a change: the pill's own render is a mutation this watches
		if (hidden === next?.heading) return;
		next = hidden ? { heading: hidden, title: hidden.textContent?.trim() || 'More options' } : null;
	}

	function reveal() {
		const section = next?.heading.closest('section');
		if (!section) return;
		const smooth = !matchMedia('(prefers-reduced-motion: reduce)').matches;
		section.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' });
	}

	$effect(() => {
		const el = scroller;
		if (!el) return;
		update();
		el.addEventListener('scroll', update, { passive: true });
		// Sections appear, grow and shrink as datasets and options change
		const resize = new ResizeObserver(update);
		resize.observe(el);
		const mutate = new MutationObserver(() => {
			for (const child of el.children) resize.observe(child);
			update();
		});
		mutate.observe(el, { childList: true, subtree: true });
		for (const child of el.children) resize.observe(child);
		return () => {
			el.removeEventListener('scroll', update);
			resize.disconnect();
			mutate.disconnect();
		};
	});
</script>

<!-- Zero-height and sticky, so the pill sits on the pane's bottom edge
     without adding space after the content -->
<div class="pointer-events-none sticky bottom-0 h-0">
	{#if next}
		<button
			type="button"
			onclick={reveal}
			class="pointer-events-auto absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 whitespace-nowrap rounded-full border bg-card px-3 py-1.5 text-xs font-bold text-foreground shadow-md transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring motion-safe:animate-in motion-safe:fade-in"
		>
			More options below: {next.title}
			<ChevronDown class="size-3.5" aria-hidden="true" />
		</button>
	{/if}
</div>
