import type maplibregl from 'maplibre-gl';
import { readTokens } from '$lib/theme/tokens';
import { NO_VALUE_COLOR } from '$lib/viz';

// Choropleth layers shared by /viz/[id] and /viz/explore.

/** Fill opacity of every choropleth feature; legend swatches use the same value. */
export const CHOROPLETH_OPACITY = 0.75;

const BASE_LINE_WIDTH = 0.75;
// Hover raises the outline instead of washing the fill out, so the value stays readable
const HOVER_LINE_WIDTH = 2.25;

export const fcSourceId = (fc: string) => `fc-${fc}`;
export const fcFillId = (fc: string) => `fc-fill-${fc}`;
export const fcLineId = (fc: string) => `fc-line-${fc}`;

/** Add the vector source plus fill and outline layers for one feature collection. */
export function addChoroplethLayers(map: maplibregl.Map, fc: string, tileUrl: string): void {
	map.addSource(fcSourceId(fc), {
		type: 'vector',
		tiles: [tileUrl],
		minzoom: 0,
		maxzoom: 12,
		promoteId: { [fc]: 'id' }
	});
	map.addLayer({
		id: fcFillId(fc),
		type: 'fill',
		source: fcSourceId(fc),
		'source-layer': fc,
		paint: { 'fill-color': NO_VALUE_COLOR, 'fill-opacity': CHOROPLETH_OPACITY }
	});
	map.addLayer({
		id: fcLineId(fc),
		type: 'line',
		source: fcSourceId(fc),
		'source-layer': fc,
		paint: {
			// Every feature keeps an outline, since ramp ends nearly vanish on the basemap (§3)
			'line-color': readTokens().edge,
			'line-width': [
				'case',
				['boolean', ['feature-state', 'hover'], false],
				HOVER_LINE_WIDTH,
				BASE_LINE_WIDTH
			]
		}
	});
}

/** Re-resolve the theme-dependent outline color after a theme change. */
export function refreshChoroplethTheme(map: maplibregl.Map, fcs: Iterable<string>): void {
	const edge = readTokens().edge;
	for (const fc of fcs) {
		if (map.getLayer(fcLineId(fc))) map.setPaintProperty(fcLineId(fc), 'line-color', edge);
	}
}
