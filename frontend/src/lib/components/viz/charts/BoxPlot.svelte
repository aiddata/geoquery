<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import type { SingleColCard } from '../chartTypes';
	import { fmt, prettyColumn } from '$lib/viz';

	interface Props {
		data: VizPayload;
		card: SingleColCard;
		onsvgready?: (svg: SVGSVGElement | null) => void;
	}
	let { data, card, onsvgready }: Props = $props();

	const TOP = 30, BOT = 160, CH = BOT - TOP;

	function niceName(col: string) { return prettyColumn(col).replace(/_/g, ' '); }

	function quantile(sorted: number[], q: number): number {
		const pos = (sorted.length - 1) * q;
		const lo = Math.floor(pos), hi = Math.ceil(pos);
		return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
	}

	function getGroups() {
		const byFc = new Map<string, number[]>();
		for (const f of Object.values(data.features)) {
			const v = Number(f[card.column]);
			if (isNaN(v)) continue;
			const fc = f.fc as string;
			if (!byFc.has(fc)) byFc.set(fc, []);
			byFc.get(fc)!.push(v);
		}
		return [...byFc.entries()].map(([fc, vals]) => {
			const sorted = [...vals].sort((a, b) => a - b);
			const q1 = quantile(sorted, 0.25), median = quantile(sorted, 0.5), q3 = quantile(sorted, 0.75);
			const iqr = q3 - q1;
			const whiskerLo = sorted.find(v => v >= q1 - 1.5 * iqr) ?? sorted[0];
			const whiskerHi = [...sorted].reverse().find(v => v <= q3 + 1.5 * iqr) ?? sorted[sorted.length - 1];
			const outliers = sorted.filter(v => v < whiskerLo || v > whiskerHi);
			return { fc, q1, median, q3, whiskerLo, whiskerHi, outliers };
		});
	}

	let svgEl = $state<SVGSVGElement | undefined>();
	$effect(() => {
		if (svgEl) onsvgready?.(svgEl);
		return () => onsvgready?.(null);
	});

	let groups = $derived(getGroups());
	let allVals = $derived(groups.flatMap(g => [...g.outliers, g.whiskerLo, g.whiskerHi]));
	let globalMin = $derived(allVals.length ? Math.min(...allVals) : 0);
	let globalMax = $derived(allVals.length ? Math.max(...allVals) : 1);
	let yRange = $derived(globalMax - globalMin || 1);
	let svgW = $derived(Math.max(240, 83 + (groups.length - 1) * 80));

	function yPos(v: number) { return BOT - ((v - globalMin) / yRange) * CH; }
	let yTicks = $derived(Array.from({ length: 4 }, (_, i) => globalMin + (i / 3) * yRange));

	let ds = $derived(data.col_dataset_titles[card.column] ?? '');
	let temporal = $derived(data.col_temporal[card.column] ?? '');
	let colPart = $derived([niceName(card.column), temporal].filter(Boolean).join(' · '));
</script>

{#if groups.length === 0}
	<p class="text-center text-sm text-muted-foreground py-10">No numeric data for this column.</p>
{:else}
	<svg bind:this={svgEl} viewBox="0 0 {svgW} 200" class="w-full" style="aspect-ratio: {svgW} / 200">
		<rect width={svgW} height="200" fill="white" />
		<text x={svgW/2} y="13" text-anchor="middle" font-size="10" font-weight="600" fill="#1e293b">{ds || niceName(card.column)}</text>
		<text x={svgW/2} y="23" text-anchor="middle" font-size="9" fill="#64748b">{colPart} — Box Plot by Group</text>
		{#each yTicks as t}
			<line x1="36" y1={yPos(t)} x2={svgW - 8} y2={yPos(t)} stroke="#f1f5f9" stroke-width="1" />
			<text x="32" y={yPos(t) + 4} text-anchor="end" font-size="8" fill="#94a3b8">{fmt(t)}</text>
		{/each}
		{#each groups as g, i}
			{@const cx = 60 + i * 80}
			<line x1={cx} y1={yPos(g.whiskerHi)} x2={cx} y2={yPos(g.whiskerLo)} stroke="#3b82f6" stroke-width="1" />
			<line x1={cx-8} y1={yPos(g.whiskerHi)} x2={cx+8} y2={yPos(g.whiskerHi)} stroke="#3b82f6" stroke-width="1" />
			<line x1={cx-8} y1={yPos(g.whiskerLo)} x2={cx+8} y2={yPos(g.whiskerLo)} stroke="#3b82f6" stroke-width="1" />
			<rect x={cx-15} y={yPos(g.q3)} width="30" height={Math.max(1, yPos(g.q1) - yPos(g.q3))}
				fill="#3b82f6" opacity="0.2" stroke="#3b82f6" stroke-width="1" />
			<line x1={cx-15} y1={yPos(g.median)} x2={cx+15} y2={yPos(g.median)} stroke="#3b82f6" stroke-width="2" />
			{#each g.outliers as o}
				<circle cx={cx} cy={yPos(o)} r="2" fill="none" stroke="#3b82f6" stroke-width="0.75" opacity="0.6">
					<title>{fmt(o)}</title>
				</circle>
			{/each}
			<text x={cx} y="178" text-anchor="middle" font-size="8" fill="#64748b">{g.fc}</text>
		{/each}
		<line x1="36" y1={TOP} x2="36" y2={BOT} stroke="#e2e8f0" stroke-width="0.5" />
		<line x1="36" y1={BOT} x2={svgW - 8} y2={BOT} stroke="#e2e8f0" stroke-width="0.5" />
	</svg>
{/if}
