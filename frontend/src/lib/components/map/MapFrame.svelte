<script lang="ts">
	import { onMount } from 'svelte';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { layers, namedFlavor } from '@protomaps/basemaps';
	import { boundaryTileUrl, fetchConfig } from '$lib/api';

	interface Props {
		class?: string;
		boundaryName?: string | null;
		boundaryBbox?: [number, number, number, number] | null;
	}

	let {
		class: className = '',
		boundaryName = null,
		boundaryBbox = null
	}: Props = $props();

	let mapContainer: HTMLDivElement;
	let map: maplibregl.Map | null = $state(null);
	let mapReady = $state(false);

	const BOUNDARY_SOURCE = 'boundary-tiles';
	const BOUNDARY_FILL_LAYER = 'boundary-fill';
	const BOUNDARY_LINE_LAYER = 'boundary-line';

	let popup: maplibregl.Popup | null = null;
	let hoveredFeatureId: number | null = null;

	onMount(() => {
		fetchConfig().then((config) => {
			map = new maplibregl.Map({
				container: mapContainer,
				style: {
					version: 8,
					glyphs:
						'https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf',
					sprite: 'https://protomaps.github.io/basemaps-assets/sprites/v4/light',
					sources: {
						protomaps: {
							type: 'vector',
							tiles: [
								`https://api.protomaps.com/tiles/v4/{z}/{x}/{y}.mvt?key=${config.protomaps_api_key}`
							],
							maxzoom: 15,
							attribution:
								'<a href="https://protomaps.com">Protomaps</a> &copy; <a href="https://openstreetmap.org">OpenStreetMap</a>'
						}
					},
					layers: layers('protomaps', namedFlavor('light'), { lang: 'en' })
				},
				center: [0, 20],
				zoom: 2
			});

			map.on('load', () => {
				mapReady = true;
			});

			map.on('error', (e) => {
				console.error('MapLibre error:', e.error?.message || e);
			});
		});

		return () => {
			map?.remove();
		};
	});

	// Add/remove vector tile layers when boundary changes
	$effect(() => {
		if (!map || !mapReady) return;
		const m = map;
		const name = boundaryName;

		if (m.getLayer(BOUNDARY_LINE_LAYER)) m.removeLayer(BOUNDARY_LINE_LAYER);
		if (m.getLayer(BOUNDARY_FILL_LAYER)) m.removeLayer(BOUNDARY_FILL_LAYER);
		if (m.getSource(BOUNDARY_SOURCE)) m.removeSource(BOUNDARY_SOURCE);

		if (!name) return;

		m.addSource(BOUNDARY_SOURCE, {
			type: 'vector',
			tiles: [boundaryTileUrl(name)],
			minzoom: 0,
			maxzoom: 12,
			promoteId: { [name]: 'id' }
		});

		m.addLayer({
			id: BOUNDARY_FILL_LAYER,
			type: 'fill',
			source: BOUNDARY_SOURCE,
			'source-layer': name,
			paint: {
				'fill-color': ['case', ['boolean', ['feature-state', 'hover'], false], '#2563eb', '#3b82f6'],
				'fill-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.45, 0.3]
			}
		});

		m.addLayer({
			id: BOUNDARY_LINE_LAYER,
			type: 'line',
			source: BOUNDARY_SOURCE,
			'source-layer': name,
			paint: {
				'line-color': '#1e40af',
				'line-width': ['case', ['boolean', ['feature-state', 'hover'], false], 3, 2]
			}
		});

		// Hover popup
		const onMouseMove = (e: maplibregl.MapLayerMouseEvent) => {
			if (!e.features || e.features.length === 0) return;
			m.getCanvas().style.cursor = 'pointer';

			const feature = e.features[0];
			const featureName = feature.properties?.name;

			// Update hover state
			if (hoveredFeatureId !== null) {
				m.setFeatureState(
					{ source: BOUNDARY_SOURCE, sourceLayer: name, id: hoveredFeatureId },
					{ hover: false }
				);
			}
			hoveredFeatureId = feature.id as number;
			m.setFeatureState(
				{ source: BOUNDARY_SOURCE, sourceLayer: name, id: hoveredFeatureId },
				{ hover: true }
			);

			if (featureName) {
				if (!popup) {
					popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
				}
				popup.setLngLat(e.lngLat).setHTML(`<strong>${featureName}</strong>`).addTo(m);
			}
		};

		const onMouseLeave = () => {
			m.getCanvas().style.cursor = '';
			if (hoveredFeatureId !== null) {
				m.setFeatureState(
					{ source: BOUNDARY_SOURCE, sourceLayer: name, id: hoveredFeatureId },
					{ hover: false }
				);
				hoveredFeatureId = null;
			}
			if (popup) {
				popup.remove();
				popup = null;
			}
		};

		m.on('mousemove', BOUNDARY_FILL_LAYER, onMouseMove);
		m.on('mouseleave', BOUNDARY_FILL_LAYER, onMouseLeave);

		return () => {
			m.off('mousemove', BOUNDARY_FILL_LAYER, onMouseMove);
			m.off('mouseleave', BOUNDARY_FILL_LAYER, onMouseLeave);
			if (popup) {
				popup.remove();
				popup = null;
			}
			hoveredFeatureId = null;
		};
	});

	// Zoom to boundary extent
	$effect(() => {
		if (!map || !mapReady || !boundaryBbox) return;
		const [west, south, east, north] = boundaryBbox;
		map.fitBounds(
			[
				[west, south],
				[east, north]
			],
			{ padding: 40, maxZoom: 12 }
		);
	});

	export function zoomIn() {
		map?.zoomIn();
	}

	export function zoomOut() {
		map?.zoomOut();
	}

</script>

<div bind:this={mapContainer} class="h-full w-full {className}"></div>
