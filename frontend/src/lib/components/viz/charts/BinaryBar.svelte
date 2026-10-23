<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import type { SingleColCard } from '../chartTypes';
	import { numericValue } from '$lib/viz';
	import { aidBase, aidTip, barInset, labelWidth, type DrawFn } from '$lib/charts/plot';
	import { columnCaption } from '$lib/charts/labels';
	import PlotFigure, { type FigureHandle } from '$lib/components/charts/PlotFigure.svelte';

	interface Props {
		data: VizPayload;
		card: SingleColCard;
		handle?: FigureHandle | null;
	}
	let { data, card, handle = $bindable() }: Props = $props();

	const LEVELS = ['Present', 'Absent'] as const;
	const ROW_H = 36;
	const MARGIN_TOP = 6;
	const MARGIN_BOTTOM = 30;
	const MIN_LABEL_PX = 34;

	interface Group {
		fc: string;
		present: number;
		absent: number;
		total: number;
	}

	interface Segment {
		fc: string;
		level: (typeof LEVELS)[number];
		i: number;
		n: number;
		share: number;
		x1: number;
		x2: number;
		mid: number;
	}

	function getGroups(): Group[] {
		const byFc = new Map<string, { present: number; absent: number }>();
		for (const f of Object.values(data.features)) {
			const v = numericValue(f[card.column]);
			if (v !== 0 && v !== 1) continue;
			const g = byFc.get(f.fc) ?? { present: 0, absent: 0 };
			if (v === 1) g.present++;
			else g.absent++;
			byFc.set(f.fc, g);
		}
		return [...byFc.entries()]
			.map(([fc, g]) => ({ fc, ...g, total: g.present + g.absent }))
			.filter((g) => g.total > 0);
	}

	let groups = $derived(getGroups());
	let caption = $derived(columnCaption(data, card.column, 'Present / absent'));

	let segments = $derived(
		groups.flatMap((g): Segment[] => {
			const present = (g.present / g.total) * 100;
			return [
				{ fc: g.fc, level: 'Present', i: 0, n: g.present, share: present, x1: 0, x2: present, mid: present / 2 },
				{ fc: g.fc, level: 'Absent', i: 1, n: g.absent, share: 100 - present, x1: present, x2: 100, mid: (present + 100) / 2 }
			];
		})
	);

	const pct = (n: number) => `${Math.round(n)}%`;

	const draw: DrawFn = ({ Plot, t, width }) => {
		const marginLeft = Math.min(200, labelWidth(t, groups.map((g) => g.fc)) + 12);
		const marginRight = 16;
		const plotWidth = width - marginLeft - marginRight;
		const height = groups.length * ROW_H + MARGIN_TOP + MARGIN_BOTTOM;
		const inset = barInset(ROW_H);
		const overall = groups.reduce((a, g) => a + g.present, 0) / groups.reduce((a, g) => a + g.total, 0);

		// One mark per level, so only the stack's outer ends are rounded (§9.4)
		const bars = LEVELS.map((level, i) =>
			Plot.barX(
				segments.filter((s) => s.i === i),
				{
					x1: 'x1',
					x2: 'x2',
					y: 'fc',
					fill: 'level',
					stroke: t.edge,
					strokeWidth: 1,
					insetTop: inset,
					insetBottom: inset,
					...(i === 0 ? { rx1: 4 } : { rx2: 4 })
				}
			)
		);
		// Labels in each level's ink, only where the segment is wide enough to hold one (§9.5)
		const labels = LEVELS.map((_, i) =>
			Plot.text(
				segments.filter((s) => s.i === i && (s.share / 100) * plotWidth >= MIN_LABEL_PX),
				{ x: 'mid', y: 'fc', text: (s: Segment) => pct(s.share), fill: t.ink[i], fontWeight: 700 }
			)
		);

		return Plot.plot({
			...aidBase(t, width, height),
			marginTop: MARGIN_TOP,
			marginBottom: MARGIN_BOTTOM,
			marginLeft,
			marginRight,
			ariaLabel: `Share of features where ${caption.subtitle.split(' — ')[0]} is present, by boundary set`,
			ariaDescription: `Across all boundary sets, ${pct(overall * 100)} of features are present.`,
			x: { domain: [0, 100], ticks: [0, 25, 50, 75, 100], tickFormat: (d: number) => `${d}%`, tickSize: 0, label: null },
			y: { domain: groups.map((g) => g.fc), padding: 0, tickSize: 0, label: null },
			color: { domain: [...LEVELS], range: t.series.slice(0, 2), legend: true },
			marks: [
				Plot.gridX([25, 50, 75, 100], { stroke: t.grid, strokeOpacity: 1 }),
				...bars,
				...labels,
				Plot.tip(
					segments,
					Plot.pointer({
						x: 'mid',
						y: 'fc',
						title: (s: Segment) => `${s.fc}\n${s.level}: ${s.n.toLocaleString()} (${s.share.toFixed(1)}%)`,
						...aidTip(t)
					})
				)
			]
		});
	};

	let table = $derived({
		columns: [
			{ key: 'fc', label: 'Boundary set' },
			{ key: 'present', label: 'Present', numeric: true },
			{ key: 'presentShare', label: 'Present %', numeric: true, format: (v: unknown) => `${(v as number).toFixed(1)}%` },
			{ key: 'absent', label: 'Absent', numeric: true },
			{ key: 'absentShare', label: 'Absent %', numeric: true, format: (v: unknown) => `${(v as number).toFixed(1)}%` }
		],
		rows: groups.map((g) => ({
			fc: g.fc,
			present: g.present,
			presentShare: (g.present / g.total) * 100,
			absent: g.absent,
			absentShare: (g.absent / g.total) * 100
		}))
	});
</script>

{#if groups.length === 0}
	<p class="py-10 text-center text-sm text-muted-foreground">No binary data for this column.</p>
{:else}
	<PlotFigure title={caption.title} subtitle={caption.subtitle} {draw} {table} bind:handle />
{/if}
