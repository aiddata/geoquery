<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import type { SingleColCard } from '../chartTypes';
	import { fmt, numericValue } from '$lib/viz';
	import { aidBase, aidTip, barInset, compact, labelWidth, niceScale, tickFormatFor, type DrawFn } from '$lib/charts/plot';
	import { columnCaption } from '$lib/charts/labels';
	import PlotFigure, { type FigureHandle } from '$lib/components/charts/PlotFigure.svelte';

	interface Props {
		data: VizPayload;
		card: SingleColCard;
		handle?: FigureHandle | null;
	}
	let { data, card, handle = $bindable() }: Props = $props();

	const TOP_N = 15;
	const ROW_H = 28;
	const MARGIN_TOP = 8;
	const MARGIN_BOTTOM = 36;

	interface Row {
		id: string;
		name: string;
		fc: string;
		value: number;
	}

	function truncate(s: string, n: number) {
		return s.length > n ? s.slice(0, n - 1) + '…' : s;
	}

	function getRanked(col: string, dir: 'top' | 'bottom'): Row[] {
		const rows: Row[] = [];
		for (const [id, f] of Object.entries(data.features)) {
			const value = numericValue(f[col]);
			if (value !== null) rows.push({ id, name: f.name, fc: f.fc, value });
		}
		rows.sort((a, b) => (dir === 'top' ? b.value - a.value : a.value - b.value));
		return rows.slice(0, TOP_N);
	}

	let dir = $derived<'top' | 'bottom'>(card.type === 'top_bar' ? 'top' : 'bottom');
	let rows = $derived(getRanked(card.column, dir));
	let caption = $derived(columnCaption(data, card.column, dir === 'top' ? 'Top values' : 'Bottom values'));

	const draw: DrawFn = ({ Plot, t, width }) => {
		const names = new Map(rows.map((r) => [r.id, truncate(r.name, 22)]));
		const values = rows.map((r) => r.value);
		const x = niceScale(Math.min(0, ...values), Math.max(0, ...values), width < 420 ? 3 : 5);
		const height = rows.length * ROW_H + MARGIN_TOP + MARGIN_BOTTOM;
		const inset = barInset(ROW_H);
		const label = (d: Row) => compact(d.value);
		const first = rows[0];

		return Plot.plot({
			...aidBase(t, width, height),
			marginTop: MARGIN_TOP,
			marginBottom: MARGIN_BOTTOM,
			marginLeft: Math.min(200, labelWidth(t, [...names.values()]) + 12),
			marginRight: 52,
			ariaLabel: `${dir === 'top' ? 'Highest' : 'Lowest'} ${rows.length} values of ${caption.title}`,
			ariaDescription: `${first.name} ranks ${dir === 'top' ? 'highest' : 'lowest'} at ${fmt(first.value)}.`,
			x: { domain: x.domain, ticks: x.ticks, tickFormat: tickFormatFor(x.ticks), tickSize: 0, label: null },
			y: { domain: rows.map((r) => r.id), padding: 0, tickSize: 0, tickFormat: (id: string) => names.get(id) ?? id, label: null },
			marks: [
				Plot.gridX(x.ticks, { stroke: t.grid, strokeOpacity: 1 }),
				// Bars at most 24px thick, the data end rounded and the baseline end square (§9.4)
				Plot.barX(rows, {
					x: 'value',
					y: 'id',
					fill: t.series[0],
					stroke: t.edge,
					strokeWidth: 1,
					insetTop: inset,
					insetBottom: inset,
					rx2: 4
				}),
				Plot.ruleX([0], { stroke: t.axis }),
				Plot.text(rows.filter((r) => r.value >= 0), { x: 'value', y: 'id', text: label, dx: 6, textAnchor: 'start', fill: t.foreground, fontWeight: 700 }),
				Plot.text(rows.filter((r) => r.value < 0), { x: 'value', y: 'id', text: label, dx: -6, textAnchor: 'end', fill: t.foreground, fontWeight: 700 }),
				Plot.tip(
					rows,
					Plot.pointerY({ x: 'value', y: 'id', title: (d: Row) => `${d.name}\n${d.fc}\n${fmt(d.value)}`, ...aidTip(t) })
				)
			]
		});
	};

	let table = $derived({
		columns: [
			{ key: 'rank', label: 'Rank', numeric: true },
			{ key: 'name', label: 'Name' },
			{ key: 'fc', label: 'Boundary set' },
			{ key: 'value', label: 'Value', numeric: true }
		],
		rows: rows.map((r, i) => ({ rank: i + 1, name: r.name, fc: r.fc, value: r.value }))
	});
</script>

{#if rows.length === 0}
	<p class="py-10 text-center text-sm text-muted-foreground">No numeric data for this column.</p>
{:else}
	<PlotFigure title={caption.title} subtitle={caption.subtitle} {draw} {table} bind:handle />
{/if}
