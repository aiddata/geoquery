import type maplibregl from 'maplibre-gl';
import { readTokens } from '$lib/theme/tokens';
import { fmt, NO_VALUE_COLOR } from '$lib/viz';
import { CHOROPLETH_OPACITY } from './choropleth';

export interface MapExportOptions {
	title: string;
	columnLabel: string | null;
	palette: string[];
	breaks: number[] | null;
	stats: { min: number; max: number; mean: number; n: number } | null;
	filename: string;
}

type RoundRectContext = CanvasRenderingContext2D & { roundRect: (...a: unknown[]) => void };

/**
 * Download the map as a PNG with a legend panel drawn in the corner.
 *
 * Canvas can't read CSS, so colors and fonts come from the resolved design
 * tokens (design-system.md §11 "Map export"): labels are `--font-ui` at 700 13px.
 * The map needs `preserveDrawingBuffer` for its canvas to be readable.
 */
export async function exportMapImage(map: maplibregl.Map, opts: MapExportOptions): Promise<void> {
	const t = readTokens();
	const uiFont = `700 13px ${t.fontUi}`;
	const titleFont = `700 15px ${t.fontHeading}`;
	// Canvas silently falls back to a default face if the webfont isn't loaded yet
	await document.fonts.load(uiFont);

	map.once('render', () => {
		const mapCanvas = map.getCanvas();
		const dpr = window.devicePixelRatio || 1;
		const cssW = mapCanvas.width / dpr;
		const cssH = mapCanvas.height / dpr;

		const out = document.createElement('canvas');
		out.width = mapCanvas.width;
		out.height = mapCanvas.height;
		const ctx = out.getContext('2d')! as RoundRectContext;
		ctx.scale(dpr, dpr);
		ctx.drawImage(mapCanvas, 0, 0, cssW, cssH);

		// ── Legend panel ───────────────────────────────────────────────
		const pad = 12;
		const swatchSz = 13;
		const rowH = 20;
		const lineH = 18;
		const panelW = 240;
		const textW = panelW - pad * 2;
		const legendRows = opts.breaks ? opts.palette.length + 1 : 0; // +1 no data

		const panelH =
			pad * 2 +
			lineH + 4 + // title
			(opts.columnLabel ? lineH + 6 : 0) +
			lineH + // "Legend" heading
			legendRows * rowH +
			(opts.stats ? 6 + lineH * 2 : 0); // "Statistics" heading + values

		const panelX = pad;
		const panelY = cssH - panelH - pad;

		ctx.save();
		ctx.globalAlpha = 0.93;
		ctx.fillStyle = t.card;
		ctx.beginPath();
		ctx.roundRect(panelX, panelY, panelW, panelH, 10);
		ctx.fill();
		ctx.restore();

		const x = panelX + pad;
		let y = panelY + pad;
		ctx.textBaseline = 'middle';

		ctx.fillStyle = t.foreground;
		ctx.font = titleFont;
		ctx.fillText(opts.title, x, y + lineH / 2, textW);
		y += lineH + 4;

		if (opts.columnLabel) {
			ctx.fillStyle = t.mutedForeground;
			ctx.font = uiFont;
			ctx.fillText(opts.columnLabel, x, y + lineH / 2, textW);
			y += lineH + 6;
		}

		ctx.fillStyle = t.foreground;
		ctx.font = uiFont;
		ctx.fillText('Legend', x, y + lineH / 2);
		y += lineH;

		const swatch = (color: string) => {
			ctx.save();
			ctx.globalAlpha = CHOROPLETH_OPACITY;
			ctx.fillStyle = color;
			ctx.beginPath();
			ctx.roundRect(x, y + (rowH - swatchSz) / 2, swatchSz, swatchSz, 2);
			ctx.fill();
			ctx.restore();
			ctx.strokeStyle = t.edge;
			ctx.lineWidth = 1;
			ctx.stroke();
		};

		if (opts.breaks) {
			const breaks = opts.breaks;
			ctx.fillStyle = t.foreground;
			for (let i = 0; i < opts.palette.length; i++) {
				swatch(opts.palette[i]);
				ctx.fillStyle = t.foreground;
				ctx.fillText(
					`${fmt(breaks[i])} – ${fmt(breaks[i + 1])}`,
					x + swatchSz + 8,
					y + rowH / 2,
					textW - swatchSz - 8
				);
				y += rowH;
			}
			swatch(NO_VALUE_COLOR);
			ctx.fillStyle = t.foreground;
			ctx.fillText('No data', x + swatchSz + 8, y + rowH / 2);
			y += rowH;
		}

		if (opts.stats) {
			const s = opts.stats;
			y += 6;
			ctx.fillStyle = t.foreground;
			ctx.fillText('Statistics', x, y + lineH / 2);
			y += lineH;
			ctx.fillStyle = t.mutedForeground;
			ctx.fillText(
				`Min ${fmt(s.min)}   Max ${fmt(s.max)}   Mean ${fmt(s.mean)}   n=${s.n.toLocaleString()}`,
				x,
				y + lineH / 2,
				textW
			);
		}

		const a = document.createElement('a');
		a.href = out.toDataURL('image/png');
		a.download = opts.filename;
		a.click();
	});
	map.triggerRepaint();
}
