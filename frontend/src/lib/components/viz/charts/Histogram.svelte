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

  const N_BINS = 20;

  function getValues(col: string): number[] {
    const out: number[] = [];
    for (const f of Object.values(data.features)) {
      const v = f[col];
      if (v !== null && v !== undefined) {
        const n = Number(v); if (!isNaN(n)) out.push(n);
      }
    }
    return out;
  }

  interface Bin { lo: number; hi: number; count: number; }

  function makeBins(vals: number[]): Bin[] {
    if (!vals.length) return [];
    let min = vals[0], max = vals[0];
    for (const v of vals) { if (v < min) min = v; if (v > max) max = v; }
    if (min === max) return [{ lo: min, hi: max, count: vals.length }];
    const w = (max - min) / N_BINS;
    const bins: Bin[] = Array.from({ length: N_BINS }, (_, i) => ({
      lo: min + i * w, hi: min + (i + 1) * w, count: 0
    }));
    for (const v of vals) {
      const i = Math.min(Math.floor((v - min) / w), N_BINS - 1);
      bins[i].count++;
    }
    return bins;
  }

  function niceName(col: string) { return prettyColumn(col).replace(/_/g, ' '); }
  function mean(vals: number[]) { return vals.reduce((a, b) => a + b, 0) / vals.length; }

  let svgEl = $state<SVGSVGElement | undefined>();
  $effect(() => {
    if (svgEl) onsvgready?.(svgEl);
    return () => onsvgready?.(null);
  });

  let vals = $derived(getValues(card.column));
  let bins = $derived(makeBins(vals));
  let maxCount = $derived(bins.reduce((a, b) => Math.max(a, b.count), 0));
  let minVal = $derived(bins.length ? bins[0].lo : 0);
  let maxVal = $derived(bins.length ? bins[bins.length - 1].hi : 0);
  let rangeVal = $derived(maxVal - minVal);
  let m = $derived(vals.length ? mean(vals) : 0);
  let meanX = $derived(rangeVal > 0 ? ((m - minVal) / rangeVal) * (N_BINS * 20) : -1);
  let ds = $derived(data.col_dataset_titles[card.column] ?? '');
  let temporal = $derived(data.col_temporal[card.column] ?? '');
  let colPart = $derived([niceName(card.column), temporal].filter(Boolean).join(' · '));
  let typeLabel = $derived('Distribution');
  let cx = $derived(7 + N_BINS * 10);
</script>

{#if vals.length === 0}
  <p class="text-center text-sm text-muted-foreground py-10">No numeric data for this column.</p>
{:else}
  <svg
    bind:this={svgEl}
    viewBox="0 0 {14 + N_BINS * 20} 148"
    class="w-full"
    style="aspect-ratio: {14 + N_BINS * 20} / 148"
    preserveAspectRatio="none"
  >
    <rect width="{14 + N_BINS * 20}" height="148" fill="white" />
    <text x={cx} y="13" text-anchor="middle" font-size="10" font-weight="600" fill="#1e293b">{ds || niceName(card.column)}</text>
    <text x={cx} y="25" text-anchor="middle" font-size="9" fill="#64748b">{colPart} — {typeLabel}</text>
    <text transform="rotate(-90, 8, 70)" text-anchor="middle" font-size="8" fill="#94a3b8">Count</text>
    {#each bins as bin, i}
      {@const barH = maxCount > 0 ? (bin.count / maxCount) * 80 : 0}
      <rect x={14 + i * 20 + 0.5} y={110 - barH} width="19" height={barH}
        fill="#3b82f6" opacity="0.72" rx="1">
        <title>{fmt(bin.lo)} – {fmt(bin.hi)}: {bin.count}</title>
      </rect>
    {/each}
    <line x1="14" y1="110" x2="{14 + N_BINS * 20}" y2="110" stroke="#e2e8f0" stroke-width="0.5" />
    {#if meanX >= 0}
      <line x1={14 + meanX} y1="28" x2={14 + meanX} y2="110"
        stroke="#ef4444" stroke-width="1.5" stroke-dasharray="3 2" opacity="0.85" />
      <text x={Math.min(14 + meanX + 3, 14 + N_BINS * 20 - 40)} y="38"
        font-size="9" fill="#ef4444" opacity="0.85">mean</text>
    {/if}
    <text x="16" y="122" font-size="8" fill="#94a3b8">{fmt(minVal)}</text>
    <text x={cx} y="122" text-anchor="middle" font-size="8" fill="#94a3b8">
      {vals.length.toLocaleString()} values · mean {fmt(m)}
    </text>
    <text x="{12 + N_BINS * 20}" y="122" text-anchor="end" font-size="8" fill="#94a3b8">{fmt(maxVal)}</text>
    <text x={cx} y="138" text-anchor="middle" font-size="7" fill="#94a3b8">Value</text>
  </svg>
{/if}
