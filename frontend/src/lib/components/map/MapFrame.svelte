<script lang="ts">
	import { onMount } from 'svelte';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { layers, namedFlavor } from '@protomaps/basemaps';
	import { boundaryTileUrl, fetchConfig } from '$lib/api';
	import { escapeHtml } from '$lib/viz';
	import type { FeatureCollection } from 'geojson';

	export interface FcStyle {
		name: string;
		color: string;
		lineWidth: number;
	}

	interface Props {
		class?: string;
		fcStyles?: FcStyle[];
		activeFcName?: string | null;
		selectedFeatureIds?: number[];
		bbox?: [number, number, number, number] | null;
		onFeatureClick?: (featureId: number) => void;
		userGeoJSON?: FeatureCollection | null;
	}

	let {
		class: className = '',
		fcStyles = [],
		activeFcName = null,
		selectedFeatureIds = [],
		bbox = null,
		onFeatureClick,
		userGeoJSON = null,
	}: Props = $props();

	let fcNames = $derived(fcStyles.map((s) => s.name));

	const USER_SOURCE = 'user-upload';
	const USER_FILL = 'user-upload-fill';
	const USER_LINE = 'user-upload-line';

	let mapContainer: HTMLDivElement;
	let map: maplibregl.Map | null = $state(null);
	let mapReady = $state(false);

	let popup: maplibregl.Popup | null = null;
	let hoveredFeatureId: number | null = null;
	let prevSelectedIds: number[] = [];

	const fcSourceId = (name: string) => `fc-tiles-${name}`;
	const fcFillId = (name: string) => `fc-fill-${name}`;
	const fcLineId = (name: string) => `fc-line-${name}`;

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

	// Sync FC tile sources/layers when fcNames changes
	$effect(() => {
		if (!map || !mapReady) return;
		const m = map;
		const names = [...fcNames];

		const existingSources = Object.keys(m.getStyle()?.sources ?? {});
		const existingFcNames = existingSources
			.filter((s) => s.startsWith('fc-tiles-'))
			.map((s) => s.slice('fc-tiles-'.length));

		for (const name of existingFcNames) {
			if (!names.includes(name)) {
				if (m.getLayer(fcLineId(name))) m.removeLayer(fcLineId(name));
				if (m.getLayer(fcFillId(name))) m.removeLayer(fcFillId(name));
				if (m.getSource(fcSourceId(name))) m.removeSource(fcSourceId(name));
			}
		}

		for (const style of fcStyles) {
			const { name, color, lineWidth } = style;
			if (existingFcNames.includes(name)) continue;

			m.addSource(fcSourceId(name), {
				type: 'vector',
				tiles: [boundaryTileUrl(name)],
				minzoom: 0,
				maxzoom: 12,
				promoteId: { [name]: 'id' }
			});

			m.addLayer({
				id: fcFillId(name),
				type: 'fill',
				source: fcSourceId(name),
				'source-layer': name,
				paint: {
					'fill-color': color,
					'fill-opacity': [
						'case',
						['boolean', ['feature-state', 'selected'], false],
						0.5,
						['boolean', ['feature-state', 'hover'], false],
						0.35,
						0.15
					]
				}
			});

			m.addLayer({
				id: fcLineId(name),
				type: 'line',
				source: fcSourceId(name),
				'source-layer': name,
				paint: {
					'line-color': color,
					'line-width': lineWidth
				}
			});
		}
	});

	// Keep paint props in sync for already-added FCs when their style metadata changes
	$effect(() => {
		if (!map || !mapReady) return;
		const m = map;
		for (const style of fcStyles) {
			const fillId = fcFillId(style.name);
			const lineId = fcLineId(style.name);
			if (m.getLayer(fillId)) {
				m.setPaintProperty(fillId, 'fill-color', style.color);
			}
			if (m.getLayer(lineId)) {
				m.setPaintProperty(lineId, 'line-color', style.color);
				m.setPaintProperty(lineId, 'line-width', style.lineWidth);
			}
		}
	});

	// Hover + click handlers for the active FC
	$effect(() => {
		if (!map || !mapReady) return;
		void fcNames; // re-run when layers are added/removed
		const m = map;
		const name = activeFcName;

		if (!name || !fcNames.includes(name)) return;

		const fillLayer = fcFillId(name);
		const src = fcSourceId(name);

		const onMouseMove = (e: maplibregl.MapLayerMouseEvent) => {
			if (!e.features?.length) return;
			if (onFeatureClick) m.getCanvas().style.cursor = 'pointer';

			const feature = e.features[0];
			const fid = feature.id as number;
			const featureName = feature.properties?.name;

			if (hoveredFeatureId !== null && hoveredFeatureId !== fid) {
				m.setFeatureState(
					{ source: src, sourceLayer: name, id: hoveredFeatureId },
					{ hover: false }
				);
			}
			hoveredFeatureId = fid;
			m.setFeatureState({ source: src, sourceLayer: name, id: fid }, { hover: true });

			if (featureName) {
				if (!popup) popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
				popup.setLngLat(e.lngLat).setHTML(`<strong>${escapeHtml(featureName)}</strong>`).addTo(m);
			}
		};

		const onMouseLeave = () => {
			m.getCanvas().style.cursor = '';
			if (hoveredFeatureId !== null) {
				m.setFeatureState(
					{ source: src, sourceLayer: name, id: hoveredFeatureId },
					{ hover: false }
				);
				hoveredFeatureId = null;
			}
			popup?.remove();
			popup = null;
		};

		const onClick = (e: maplibregl.MapLayerMouseEvent) => {
			if (!e.features?.length || !onFeatureClick) return;
			onFeatureClick(e.features[0].id as number);
		};

		m.on('mousemove', fillLayer, onMouseMove);
		m.on('mouseleave', fillLayer, onMouseLeave);
		m.on('click', fillLayer, onClick);

		return () => {
			m.off('mousemove', fillLayer, onMouseMove);
			m.off('mouseleave', fillLayer, onMouseLeave);
			m.off('click', fillLayer, onClick);
			if (hoveredFeatureId !== null) {
				m.setFeatureState(
					{ source: src, sourceLayer: name, id: hoveredFeatureId },
					{ hover: false }
				);
				hoveredFeatureId = null;
			}
			popup?.remove();
			popup = null;
		};
	});

	// Sync selected feature IDs as feature state on the active FC
	$effect(() => {
		if (!map || !mapReady || !activeFcName) return;
		const m = map;
		const name = activeFcName;
		const src = fcSourceId(name);
		const ids = [...selectedFeatureIds];

		for (const id of prevSelectedIds) {
			m.setFeatureState({ source: src, sourceLayer: name, id }, { selected: false });
		}
		for (const id of ids) {
			m.setFeatureState({ source: src, sourceLayer: name, id }, { selected: true });
		}
		prevSelectedIds = ids;
	});

	// Zoom to bbox
	$effect(() => {
		if (!map || !mapReady || !bbox) return;
		const [west, south, east, north] = bbox;
		map.fitBounds(
			[
				[west, south],
				[east, north]
			],
			{ padding: 40, maxZoom: 12 }
		);
	});

	// Sync user-uploaded GeoJSON layer
	$effect(() => {
		if (!map || !mapReady) return;
		const m = map;
		const geojson = userGeoJSON;

		if (!geojson) {
			if (m.getLayer(USER_FILL)) m.removeLayer(USER_FILL);
			if (m.getLayer(USER_LINE)) m.removeLayer(USER_LINE);
			if (m.getSource(USER_SOURCE)) m.removeSource(USER_SOURCE);
			return;
		}

		if (m.getSource(USER_SOURCE)) {
			(m.getSource(USER_SOURCE) as maplibregl.GeoJSONSource).setData(geojson);
		} else {
			m.addSource(USER_SOURCE, { type: 'geojson', data: geojson });
			m.addLayer({
				id: USER_FILL,
				type: 'fill',
				source: USER_SOURCE,
				paint: { 'fill-color': '#f97316', 'fill-opacity': 0.25 },
			});
			m.addLayer({
				id: USER_LINE,
				type: 'line',
				source: USER_SOURCE,
				paint: { 'line-color': '#ea580c', 'line-width': 2 },
			});
		}
	});

	export function zoomIn() {
		map?.zoomIn();
	}

	export function zoomOut() {
		map?.zoomOut();
	}
</script>

<div bind:this={mapContainer} class="h-full w-full {className}"></div>
