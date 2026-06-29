<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import type { ScatterCard } from '../chartTypes';
	import { fmt, prettyColumn } from '$lib/viz';

	interface Props {
		data: VizPayload;
		card: ScatterCard;
		highlightedFeature?: string | null;
		onHighlight?: (name: string | null) => void;
		onsvgready?: (svg: SVGSVGElement | null) => void;
	}
	let { data, card, highlightedFeature = null, onHighlight, onsvgready }: Props = $props();

	const W = 340, H = 280;
	const LEFT = 44, RIGHT = 300, TOP = 20, BOT = 240;
	const CW = RIGHT - LEFT, CH = BOT - TOP;
	const FC_COLORS = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899'];

	function niceName(col: string) { return prettyColumn(col).replace(/_/g, ' '); }

	let svgEl = $state<SVGSVGElement | undefined>();
	$effect(() => {
		if (svgEl) onsvgready?.(svgEl);
		return () => onsvgready?.(null);
	});

	function getPoints() {
		const fcList = [...new Set(Object.values(data.features).map(f => f.fc as string))].sort();
		return Object.values(data.features).flatMap(f => {
			const x = Number(f[card.xCol]), y = Number(f[card.yCol]);
			if (isNaN(x) || isNaN(y)) return [];
			return [{ x, y, name: f.name as string, color: FC_COLORS[fcList.indexOf(f.fc as string) % FC_COLORS.length] }];
		});
	}

	let points = $derived(getPoints());
	let xs = $derived(points.map(p => p.x));
	let ys = $derived(points.map(p => p.y));
	let xMin = $derived(xs.length ? Math.min(...xs) : 0);
	let xMax = $derived(xs.length ? Math.max(...xs) : 1);
	let yMin = $derived(ys.length ? Math.min(...ys) : 0);
	let yMax = $derived(ys.length ? Math.max(...ys) : 1);
	let xRange = $derived(xMax - xMin || 1);
	let yRange = $derived(yMax - yMin || 1);

	function px(x: number) { return LEFT + ((x - xMin) / xRange) * CW; }
	function py(y: number) { return BOT - ((y - yMin) / yRange) * CH; }

	let xTicks = $derived(Array.from({ length: 4 }, (_, i) => xMin + (i / 3) * xRange));
	let yTicks = $derived(Array.from({ length: 4 }, (_, i) => yMin + (i / 3) * yRange));

	let dsX = $derived(data.col_dataset_titles[card.xCol] ?? '');
	let dsY = $derived(data.col_dataset_titles[card.yCol] ?? '');
	let titleLine1 = $derived([dsX, dsY].filter(Boolean).join(' × ') || 'Scatter Plot');
	let titleLine2 = $derived(`${niceName(card.xCol)} vs ${niceName(card.yCol)}`);
</script>

{#if points.length === 0}
	<p class="text-center text-sm text-muted-foreground py-10">No numeric data for selected columns.</p>
{:else}
	<svg bind:this={svgEl} viewBox="0 0 {W} {H}" class="w-full" style="aspect-ratio: {W} / {H}">
		<rect width={W} height={H} fill="white" />
		<text x={W/2} y="12" text-anchor="middle" font-size="10" font-weight="600" fill="#1e293b">{titleLine1}</text>
		<text x={(LEFT+RIGHT)/2} y="22" text-anchor="middle" font-size="9" fill="#64748b">{titleLine2}</text>
		{#each yTicks as t}
			<line x1={LEFT} y1={py(t)} x2={RIGHT} y2={py(t)} stroke="#f1f5f9" stroke-width="1" />
			<text x={LEFT-4} y={py(t)+4} text-anchor="end" font-size="8" fill="#94a3b8">{fmt(t)}</text>
		{/each}
		{#each xTicks as t}
			<line x1={px(t)} y1={TOP} x2={px(t)} y2={BOT} stroke="#f1f5f9" stroke-width="1" />
			<text x={px(t)} y={BOT+10} text-anchor="middle" font-size="8" fill="#94a3b8">{fmt(t)}</text>
		{/each}
		{#each points as p}
			<circle cx={px(p.x)} cy={py(p.y)} r="3" fill={p.color}
				opacity={highlightedFeature === null || highlightedFeature === p.name ? 0.75 : 0.12}
				style="cursor: pointer"
				onclick={() => onHighlight?.(highlightedFeature === p.name ? null : p.name)}>
				<title>{p.name}: ({fmt(p.x)}, {fmt(p.y)})</title>
			</circle>
		{/each}
		<line x1={LEFT} y1={TOP} x2={LEFT} y2={BOT} stroke="#e2e8f0" stroke-width="0.5" />
		<line x1={LEFT} y1={BOT} x2={RIGHT} y2={BOT} stroke="#e2e8f0" stroke-width="0.5" />
		<text x={(LEFT+RIGHT)/2} y={H-4} text-anchor="middle" font-size="8" fill="#94a3b8">{niceName(card.xCol)}</text>
		<text transform="rotate(-90, 10, {(TOP+BOT)/2})" x="10" y={(TOP+BOT)/2}
			text-anchor="middle" font-size="8" fill="#94a3b8">{niceName(card.yCol)}</text>
	</svg>
{/if}
