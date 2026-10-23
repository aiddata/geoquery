import notoSans700Url from '@fontsource/noto-sans/files/noto-sans-latin-700-normal.woff2?url';
import type { FigureHandle } from '$lib/components/charts/PlotFigure.svelte';
import { readTokens, type Tokens } from '$lib/theme/tokens';
import { SYMBOLS } from './plot';

type Legend = { label: string; color: string; symbol?: string }[];
type ScaleDescriptor = { type?: string; domain?: unknown[]; range?: unknown[] };
type PlotElement = (SVGSVGElement | HTMLElement) & { scale?: (name: string) => ScaleDescriptor | undefined };

const SCALE = 2;
const PAD = 24;

let fontFace: Promise<string> | null = null;

/**
 * An SVG drawn through an <img> can't see the page's webfonts, so the exported SVG carries
 * Noto Sans 700 (the chart label face) inline. Fetched once, then cached.
 */
function embeddedFontFace(): Promise<string> {
	fontFace ??= fetch(notoSans700Url)
		.then((r) => r.arrayBuffer())
		.then((buf) => {
			let binary = '';
			const bytes = new Uint8Array(buf);
			for (let i = 0; i < bytes.length; i += 0x8000) {
				binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
			}
			return `@font-face{font-family:"Noto Sans";font-weight:700;src:url(data:font/woff2;base64,${btoa(binary)}) format("woff2");}`;
		})
		.catch(() => '');
	return fontFace;
}

/** Plot's legend is HTML above the SVG, so rebuild it from the plot's scales for the image. */
function legendOf(plot: PlotElement): Legend {
	if (!(plot instanceof HTMLElement) || !plot.querySelector(':scope > div')) return [];
	const color = plot.scale?.('color');
	if (!color?.domain || !color.range) return [];
	const symbol = plot.scale?.('symbol');
	const colors = color.range.map(String);
	if (color.type === 'threshold') {
		const d = color.domain.map(Number);
		return colors.map((c, i) => ({
			color: c,
			label: i === 0 ? `< ${d[0]}` : i === d.length ? `≥ ${d[d.length - 1]}` : `${d[i - 1]} to ${d[i]}`
		}));
	}
	return color.domain.map((label, i) => ({
		label: String(label),
		color: colors[i % colors.length],
		// Plot reports symbols as d3 symbol objects; the charts always assign SYMBOLS in order
		symbol: symbol?.domain ? SYMBOLS[i % SYMBOLS.length] : undefined
	}));
}

function drawSymbol(ctx: CanvasRenderingContext2D, symbol: string | undefined, x: number, y: number, r: number) {
	ctx.beginPath();
	if (symbol === 'circle') ctx.arc(x, y, r, 0, Math.PI * 2);
	else if (symbol === 'diamond') {
		ctx.moveTo(x, y - r * 1.2);
		ctx.lineTo(x + r * 1.2, y);
		ctx.lineTo(x, y + r * 1.2);
		ctx.lineTo(x - r * 1.2, y);
		ctx.closePath();
	} else if (symbol === 'triangle') {
		ctx.moveTo(x, y - r * 1.15);
		ctx.lineTo(x + r * 1.15, y + r * 0.85);
		ctx.lineTo(x - r * 1.15, y + r * 0.85);
		ctx.closePath();
	} else ctx.rect(x - r, y - r, r * 2, r * 2);
	ctx.fill();
	ctx.stroke();
}

async function svgImage(svg: SVGSVGElement): Promise<HTMLImageElement | null> {
	const clone = svg.cloneNode(true) as SVGSVGElement;
	clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
	const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
	style.textContent = await embeddedFontFace();
	clone.insertBefore(style, clone.firstChild);
	const url = URL.createObjectURL(
		new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml;charset=utf-8' })
	);
	return new Promise((resolve) => {
		const img = new Image();
		img.onload = () => resolve(img);
		img.onerror = () => resolve(null);
		img.src = url;
	}).finally(() => URL.revokeObjectURL(url)) as Promise<HTMLImageElement | null>;
}

/**
 * Render a drawn chart to PNG: a card-colored panel with the title, subtitle and legend,
 * then the chart. Colors come from the current theme's tokens.
 */
export async function exportPng(handle: FigureHandle): Promise<Blob | null> {
	const plot = handle.plot as PlotElement;
	const svg = plot instanceof SVGSVGElement ? plot : plot.querySelector<SVGSVGElement>(':scope > svg');
	if (!svg) return null;

	const t: Tokens = readTokens();
	const titleFont = `700 17px ${t.fontHeading}`;
	const bodyFont = `400 14px ${t.fontBody}`;
	const uiFont = `700 13px ${t.fontUi}`;
	await Promise.all([document.fonts.load(bodyFont), document.fonts.load(uiFont)]);

	const img = await svgImage(svg);
	if (!img) return null;
	const w = svg.width.baseVal.value || svg.viewBox.baseVal.width;
	const h = svg.height.baseVal.value || svg.viewBox.baseVal.height;
	const legend = legendOf(plot);

	// Lay the legend out in rows that fit the chart width
	const measure = document.createElement('canvas').getContext('2d')!;
	measure.font = uiFont;
	const legendRows: Legend[] = [];
	let row: Legend = [];
	let rowW = 0;
	for (const item of legend) {
		const itemW = 22 + measure.measureText(item.label).width + 16;
		if (row.length && rowW + itemW > w) {
			legendRows.push(row);
			row = [];
			rowW = 0;
		}
		row.push(item);
		rowW += itemW;
	}
	if (row.length) legendRows.push(row);

	const headerH = 24 + (handle.subtitle ? 22 : 0) + (legendRows.length ? 8 + legendRows.length * 22 : 0) + 12;
	const canvas = document.createElement('canvas');
	canvas.width = (w + PAD * 2) * SCALE;
	canvas.height = (h + headerH + PAD * 2) * SCALE;
	const ctx = canvas.getContext('2d')!;
	ctx.scale(SCALE, SCALE);
	ctx.fillStyle = t.card;
	ctx.fillRect(0, 0, w + PAD * 2, h + headerH + PAD * 2);

	let y = PAD;
	ctx.textBaseline = 'top';
	ctx.fillStyle = t.foreground;
	ctx.font = titleFont;
	ctx.fillText(handle.title, PAD, y, w);
	y += 24;
	if (handle.subtitle) {
		ctx.fillStyle = t.mutedForeground;
		ctx.font = bodyFont;
		ctx.fillText(handle.subtitle, PAD, y, w);
		y += 22;
	}
	if (legendRows.length) {
		y += 8;
		ctx.font = uiFont;
		ctx.textBaseline = 'middle';
		ctx.strokeStyle = t.edge;
		ctx.lineWidth = 1;
		for (const items of legendRows) {
			let x = PAD;
			for (const item of items) {
				ctx.fillStyle = item.color;
				drawSymbol(ctx, item.symbol, x + 7, y + 9, 6);
				ctx.fillStyle = t.foreground;
				ctx.fillText(item.label, x + 22, y + 9);
				x += 22 + ctx.measureText(item.label).width + 16;
			}
			y += 22;
		}
	}
	ctx.drawImage(img, PAD, PAD + headerH, w, h);

	return new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
}
