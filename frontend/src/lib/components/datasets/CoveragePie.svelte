<script lang="ts">
	// A circle filled clockwise from the top to `fraction` (0 to 1). Decorative:
	// whatever uses it says the value in words.
	interface Props {
		fraction: number;
		class?: string;
	}

	let { fraction, class: className = 'size-3.5' }: Props = $props();

	const R = 6;
	const wedge = $derived.by(() => {
		const f = Math.min(Math.max(fraction, 0), 1);
		if (f <= 0 || f >= 1) return null;
		const angle = f * 2 * Math.PI;
		const x = 7 + R * Math.sin(angle);
		const y = 7 - R * Math.cos(angle);
		return `M7 7 L7 ${7 - R} A${R} ${R} 0 ${f > 0.5 ? 1 : 0} 1 ${x.toFixed(3)} ${y.toFixed(3)} Z`;
	});
</script>

<svg viewBox="0 0 14 14" class={className} aria-hidden="true" focusable="false">
	<circle cx="7" cy="7" r={R} fill={fraction >= 1 ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="1.5" />
	{#if wedge}<path d={wedge} fill="currentColor" />{/if}
</svg>
