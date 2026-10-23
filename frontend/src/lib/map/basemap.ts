import type maplibregl from 'maplibre-gl';
import type { StyleSpecification } from 'maplibre-gl';
import { layers, namedFlavor } from '@protomaps/basemaps';
import { resolvedTheme, type ResolvedTheme } from '$lib/stores/theme';

export const BASEMAP_SOURCE = 'protomaps';

const ASSETS = 'https://protomaps.github.io/basemaps-assets';
const DEFAULT_ATTRIBUTION =
	'<a href="https://protomaps.com">Protomaps</a> &copy; <a href="https://openstreetmap.org">OpenStreetMap</a>';

/** The Protomaps basemap in the flavor matching the app theme. */
export function basemapStyle(
	theme: ResolvedTheme,
	apiKey: string,
	attribution = DEFAULT_ATTRIBUTION
): StyleSpecification {
	return {
		version: 8,
		glyphs: `${ASSETS}/fonts/{fontstack}/{range}.pbf`,
		sprite: `${ASSETS}/sprites/v4/${theme}`,
		sources: {
			[BASEMAP_SOURCE]: {
				type: 'vector',
				tiles: [`https://api.protomaps.com/tiles/v4/{z}/{x}/{y}.mvt?key=${apiKey}`],
				maxzoom: 15,
				attribution
			}
		},
		layers: layers(BASEMAP_SOURCE, namedFlavor(theme), { lang: 'en' })
	};
}

/**
 * Swap the basemap whenever the resolved theme changes, keeping every source and
 * layer the app added on top. `onApplied` runs once the new style is in place, so
 * callers can re-resolve token colors (MapLibre paint can't read CSS variables).
 * Returns an unsubscribe function.
 */
export function followTheme(
	map: maplibregl.Map,
	apiKey: string,
	onApplied: () => void,
	attribution = DEFAULT_ATTRIBUTION
): () => void {
	let current: ResolvedTheme | null = null;
	return resolvedTheme.subscribe((theme) => {
		if (current === null) {
			current = theme; // the map was created with this theme
			return;
		}
		if (theme === current) return;
		current = theme;

		map.setStyle(basemapStyle(theme, apiKey, attribution), {
			transformStyle: (prev, next) => {
				if (!prev) return next;
				const basemapIds = new Set(next.layers.map((l) => l.id));
				const own = prev.layers.filter(
					(l) => !basemapIds.has(l.id) && !('source' in l && l.source === BASEMAP_SOURCE)
				);
				const sources = { ...next.sources };
				for (const [id, src] of Object.entries(prev.sources)) {
					if (id !== BASEMAP_SOURCE) sources[id] = src;
				}
				return { ...next, sources, layers: [...next.layers, ...own] };
			}
		});

		if (map.isStyleLoaded()) onApplied();
		else map.once('style.load', onApplied);
	});
}
