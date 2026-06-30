<script lang="ts">
  import type { VizPayload } from '$lib/api';
  import type { SingleColCard } from '../chartTypes';
  import { fmt, fieldLabel } from '$lib/viz';

  interface Props {
    data: VizPayload;
    card: SingleColCard;
    onsvgready?: (svg: SVGSVGElement | null) => void;
  }
  let { data, card, onsvgready }: Props = $props();

  const TOP_N = 15;

  function truncate(s: string, n: number) { return s.length > n ? s.slice(0, n - 1) + '…' : s; }

  function getRanked(col: string, dir: 'top' | 'bottom') {
    const rows: { name: string; v: number }[] = [];
    for (const f of Object.values(data.features)) {
      const v = Number(f[col]); if (!isNaN(v)) rows.push({ name: f.name as string, v });
    }
    rows.sort((a, b) => dir === 'top' ? b.v - a.v : a.v - b.v);
    return rows.slice(0, TOP_N);
  }

  let svgEl = $state<SVGSVGElement | undefined>();
  $effect(() => {
    if (svgEl) onsvgready?.(svgEl);
    return () => onsvgready?.(null);
  });

  let dir = $derived<'top' | 'bottom'>(card.type === 'top_bar' ? 'top' : 'bottom');
  let rows = $derived(getRanked(card.column, dir));
  let maxV = $derived(rows.reduce((a, r) => Math.max(a, Math.abs(r.v)), 0));
  let barColor = $derived(card.type === 'top_bar' ? '#3b82f6' : '#fb923c');
  let svgH = $derived(rows.length * 22 + 42);
  let ds = $derived(data.col_dataset_titles[card.column] ?? '');
  let temporal = $derived(data.col_temporal[card.column] ?? '');
  let colPart = $derived([fieldLabel(card.column), temporal].filter(Boolean).join(' · '));
  let typeLabel = $derived(card.type === 'top_bar' ? 'Top Values' : 'Bottom Values');
</script>

{#if rows.length === 0}
  <p class="text-center text-sm text-muted-foreground py-10">No numeric data for this column.</p>
{:else}
  <svg
    bind:this={svgEl}
    viewBox="0 0 400 {svgH}"
    style="width: 100%; aspect-ratio: 400 / {svgH}"
  >
    <rect width="400" height={svgH} fill="white" />
    <text x="200" y="13" text-anchor="middle" font-size="10" font-weight="600" fill="#1e293b">{ds || fieldLabel(card.column)}<title>{ds || fieldLabel(card.column)}</title></text>
    <text x="200" y="25" text-anchor="middle" font-size="9" fill="#64748b">{colPart} — {typeLabel}<title>{colPart}</title></text>
    {#each rows as row, i}
      {@const barW = maxV > 0 ? (Math.abs(row.v) / maxV) * 182 : 0}
      <text x="25" y="{32 + i * 22 + 11}" dominant-baseline="middle" text-anchor="end" font-size="9" fill="#94a3b8">{i + 1}.</text>
      <text x="150" y="{32 + i * 22 + 11}" dominant-baseline="middle" text-anchor="end" font-size="9" fill="#64748b">{truncate(row.name, 22)}<title>{row.name}</title></text>
      <rect x="157" y="{32 + i * 22 + 3}" width="182" height="16" rx="2" fill="#f1f5f9" />
      <rect x="157" y="{32 + i * 22 + 3}" width={barW} height="16" rx="2" fill={barColor} opacity="0.8" />
      <text x="396" y="{32 + i * 22 + 11}" dominant-baseline="middle" text-anchor="end" font-size="9" fill="#1e293b" font-family="monospace">{fmt(row.v)}</text>
    {/each}
    <text x="339" y="{svgH - 6}" text-anchor="end" font-size="7" fill="#94a3b8">Value →</text>
  </svg>
{/if}
