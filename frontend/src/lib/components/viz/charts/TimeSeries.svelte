<script lang="ts">
  import type { VizPayload } from '$lib/api';
  import type { TimeSeriesCard } from '../chartTypes';
  import { getTemporalSeries, fmt } from '$lib/viz';

  interface Props {
    data: VizPayload;
    card: TimeSeriesCard;
    highlightedFeature?: string | null;
    onHighlight?: (name: string | null) => void;
    onsvgready?: (svg: SVGSVGElement | null) => void;
  }
  let { data, card, highlightedFeature = null, onHighlight, onsvgready }: Props = $props();

  const W = 480, H = 200;
  const LEFT = 48, RIGHT = 460, TOP = 30, BOT = 160;
  const CW = RIGHT - LEFT, CH = BOT - TOP;

  let svgEl = $state<SVGSVGElement | undefined>();
  $effect(() => {
    if (svgEl) onsvgready?.(svgEl);
    return () => onsvgready?.(null);
  });

  let series = $derived(getTemporalSeries(data, card.datasetKey));

  function getFeatureLines() {
    if (!series.length) return [];
    return Object.values(data.features).slice(0, 50).map(f => ({
      name: f.name as string,
      values: series.map(e => { const v = Number(f[e.col]); return isNaN(v) ? null : v; }),
    }));
  }

  let featureLines = $derived(getFeatureLines());
  let means = $derived(series.map(e => e.mean));
  let mins = $derived(series.map(e => e.min));
  let maxs = $derived(series.map(e => e.max));
  let globalMin = $derived(series.length ? Math.min(...series.map(e => e.min)) : 0);
  let globalMax = $derived(series.length ? Math.max(...series.map(e => e.max)) : 1);
  let yRange = $derived(globalMax - globalMin || 1);

  function xPos(i: number) { return LEFT + (series.length > 1 ? (i / (series.length - 1)) * CW : CW / 2); }
  function yPos(v: number) { return BOT - ((v - globalMin) / yRange) * CH; }

  function toPolyline(values: (number | null)[]) {
    return values.flatMap((v, i) => v !== null ? [`${xPos(i).toFixed(1)},${yPos(v).toFixed(1)}`] : []).join(' ');
  }

  function bandPath() {
    const top = series.map((_, i) => `${xPos(i).toFixed(1)},${yPos(maxs[i]).toFixed(1)}`).join(' ');
    const bot = [...series.map((_, i) => `${xPos(i).toFixed(1)},${yPos(mins[i]).toFixed(1)}`)].reverse().join(' ');
    return `M ${top.split(' ')[0]} L ${top} L ${bot} Z`;
  }

  let yTicks = $derived(Array.from({ length: 4 }, (_, i) => ({
    v: globalMin + (i / 3) * yRange,
    y: yPos(globalMin + (i / 3) * yRange)
  })));
  let xLabelRotate = $derived(series.length > 6);
  let dsTitle = $derived(data.col_dataset_titles[series[0]?.col ?? ''] ?? card.datasetKey);
</script>

{#if series.length < 2}
  <p class="text-center text-sm text-muted-foreground py-10">Not enough temporal columns in this dataset group.</p>
{:else}
  <svg bind:this={svgEl} viewBox="0 0 {W} {H}" class="w-full" style="aspect-ratio: {W} / {H}">
    <rect width={W} height={H} fill="white" />
    <text x={W/2} y="13" text-anchor="middle" font-size="10" font-weight="600" fill="#1e293b">{dsTitle}</text>
    <text x={W/2} y="23" text-anchor="middle" font-size="9" fill="#64748b">Time Series — {card.aggregateMode === 'all' ? 'all features' : card.aggregateMode === 'mean' ? 'mean' : 'mean ± range'}</text>

    {#each yTicks as t}
      <line x1={LEFT} y1={t.y} x2={RIGHT} y2={t.y} stroke="#f1f5f9" stroke-width="1" />
      <text x={LEFT - 4} y={t.y + 4} text-anchor="end" font-size="8" fill="#94a3b8">{fmt(t.v)}</text>
    {/each}

    {#if card.aggregateMode === 'band'}
      <path d={bandPath()} fill="#3b82f6" opacity="0.10" />
    {/if}

    {#if card.aggregateMode === 'all'}
      {#each featureLines as fl}
        <polyline points={toPolyline(fl.values)} fill="none"
          stroke={highlightedFeature === fl.name ? '#1d4ed8' : '#94a3b8'}
          stroke-width={highlightedFeature === fl.name ? 1.5 : 0.75}
          opacity={highlightedFeature === null || highlightedFeature === fl.name ? 0.6 : 0.08}
          style="cursor: pointer"
          onclick={() => onHighlight?.(highlightedFeature === fl.name ? null : fl.name)}>
          <title>{fl.name}</title>
        </polyline>
      {/each}
    {/if}

    <polyline points={toPolyline(means)} fill="none" stroke="#3b82f6" stroke-width="2" />
    {#each means as m, i}
      <circle cx={xPos(i)} cy={yPos(m)} r="2.5" fill="#3b82f6">
        <title>{series[i].temporal}: {fmt(m)}</title>
      </circle>
    {/each}

    {#each series as e, i}
      <text x={xPos(i)} y={BOT + (xLabelRotate ? 6 : 12)}
        text-anchor={xLabelRotate ? 'end' : 'middle'} font-size="8" fill="#94a3b8"
        transform={xLabelRotate ? `rotate(-40, ${xPos(i)}, ${BOT + 6})` : undefined}
      >{e.temporal}</text>
    {/each}

    <line x1={LEFT} y1={TOP} x2={LEFT} y2={BOT} stroke="#e2e8f0" stroke-width="0.5" />
    <line x1={LEFT} y1={BOT} x2={RIGHT} y2={BOT} stroke="#e2e8f0" stroke-width="0.5" />
  </svg>
{/if}
