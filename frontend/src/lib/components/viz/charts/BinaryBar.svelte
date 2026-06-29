<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import type { SingleColCard } from '../chartTypes';
	import { prettyColumn } from '$lib/viz';

	interface Props {
		data: VizPayload;
		card: SingleColCard;
		onsvgready?: (svg: SVGSVGElement | null) => void;
	}
	let { data, card, onsvgready }: Props = $props();

	const W = 320;
	const LEFT = 70, RIGHT = 300, BAR_H = 18, ROW_H = 30;

	function niceName(col: string) { return prettyColumn(col).replace(/_/g, ' '); }

	let svgEl = $state<SVGSVGElement | undefined>();
	$effect(() => {
		if (svgEl) onsvgready?.(svgEl);
		return () => onsvgready?.(null);
	});

	function getGroups() {
		const byFc = new Map<string, { present: number; absent: number }>();
		for (const f of Object.values(data.features)) {
			const v = Number(f[card.column]);
			if (v !== 0 && v !== 1) continue;
			const fc = f.fc as string;
			if (!byFc.has(fc)) byFc.set(fc, { present: 0, absent: 0 });
			const g = byFc.get(fc)!;
			if (v === 1) g.present++; else g.absent++;
		}
		return [...byFc.entries()]
			.map(([fc, { present, absent }]) => ({ fc, present, absent, total: present + absent }))
			.filter(g => g.total > 0);
	}

	let groups = $derived(getGroups());
	let H = $derived(Math.max(120, groups.length * ROW_H + 60));
	let ds = $derived(data.col_dataset_titles[card.column] ?? '');
	let temporal = $derived(data.col_temporal[card.column] ?? '');
	let colPart = $derived([niceName(card.column), temporal].filter(Boolean).join(' · '));

	function barW(n: number, total: number) { return (n / total) * (RIGHT - LEFT); }
</script>

{#if groups.length === 0}
	<p class="text-center text-sm text-muted-foreground py-10">No binary data for this column.</p>
{:else}
	<svg bind:this={svgEl} viewBox="0 0 {W} {H}" class="w-full" style="aspect-ratio: {W} / {H}">
		<rect width={W} height={H} fill="white" />
		<text x={W/2} y="13" text-anchor="middle" font-size="10" font-weight="600" fill="#1e293b">{ds || niceName(card.column)}</text>
		<text x={W/2} y="23" text-anchor="middle" font-size="9" fill="#64748b">{colPart} — Present / Absent</text>
		{#each groups as g, i}
			{@const y = 36 + i * ROW_H}
			{@const pw = barW(g.present, g.total)}
			{@const aw = barW(g.absent, g.total)}
			{@const pct = Math.round((g.present / g.total) * 100)}
			<text x={LEFT - 4} y={y + BAR_H/2 + 4} text-anchor="end" font-size="8" fill="#64748b">{g.fc}</text>
			<rect x={LEFT} y={y} width={pw} height={BAR_H} fill="#22c55e" />
			<rect x={LEFT + pw} y={y} width={aw} height={BAR_H} fill="#ef4444" />
			<text x={LEFT + pw + 3} y={y + BAR_H/2 + 4} font-size="8" fill="#475569">{pct}%</text>
		{/each}
		<line x1={LEFT} y1="34" x2={LEFT} y2={H - 16} stroke="#e2e8f0" stroke-width="0.5" />
		<line x1={RIGHT} y1="34" x2={RIGHT} y2={H - 16} stroke="#e2e8f0" stroke-width="0.5" />
		<text x={LEFT} y={H - 6} text-anchor="middle" font-size="7" fill="#94a3b8">0%</text>
		<text x={RIGHT} y={H - 6} text-anchor="middle" font-size="7" fill="#94a3b8">100%</text>
		<rect x={LEFT+8} y={H-14} width="8" height="8" fill="#22c55e" />
		<text x={LEFT+18} y={H-7} font-size="7" fill="#64748b">Present</text>
		<rect x={LEFT+60} y={H-14} width="8" height="8" fill="#ef4444" />
		<text x={LEFT+70} y={H-7} font-size="7" fill="#64748b">Absent</text>
	</svg>
{/if}
