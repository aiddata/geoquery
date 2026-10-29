<script lang="ts">
	import { onMount } from 'svelte';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { get } from 'svelte/store';
	import { boundaryTileUrl, multiBoundaryTileUrl, MULTI_TILE_LAYER } from '$lib/api';
	import { unionBbox, type Bbox } from '$lib/utils/bbox';
	import { protomapsApiKey } from '$lib/map/protomapsKey';
	import { basemapStyle, followTheme } from '$lib/map/basemap';
	import { resolvedTheme } from '$lib/stores/theme';
	import { readTokens, resolveColor } from '$lib/theme/tokens';
	import { escapeHtml } from '$lib/viz';
	import type { FeatureCollection } from 'geojson';

	export interface FcStyle {
		id: number;
		name: string;
		/** Extent of the collection; tiles outside it are never requested. */
		bbox: Bbox | null;
		/** A CSS color or `var(--token)`; resolved before it reaches MapLibre. */
		color: string;
		lineWidth: number;
	}

	interface Props {
		class?: string;
		fcStyles?: FcStyle[];
		activeFcName?: string | null;
		selectedFeatureIds?: number[];
		bbox?: Bbox | null;
		onFeatureClick?: (featureId: number) => void;
		onZoomChange?: (zoom: number) => void;
		userGeoJSON?: FeatureCollection | null;
	}

	let {
		class: className = '',
		fcStyles = [],
		activeFcName = null,
		selectedFeatureIds = [],
		bbox = null,
		onFeatureClick,
		onZoomChange,
		userGeoJSON = null,
	}: Props = $props();

	let fcNames = $derived(fcStyles.map((s) => s.name));

	const USER_SOURCE = 'user-upload';
	const USER_FILL = 'user-upload-fill';
	const USER_LINE = 'user-upload-line';

	let mapContainer: HTMLDivElement;
	let map: maplibregl.Map | null = $state(null);
	let mapReady = $state(false);
	// Bumped after a theme change swaps the basemap, so token colors and feature state are re-applied
	let themeTick = $state(0);

	let popup: maplibregl.Popup | null = null;
	let hoveredFeatureId: number | null = null;
	let prevSelectedIds: number[] = [];

	const fcSourceId = (name: string) => `fc-tiles-${name}`;
	const fcFillId = (name: string) => `fc-fill-${name}`;
	const fcLineId = (name: string) => `fc-line-${name}`;
	const fcCasingId = (name: string) => `fc-casing-${name}`;

	// Two or more boundaries share one source: a single tile request per map tile
	// instead of one per boundary, styled per boundary on each feature's fc_id.
	// Hover, click and selection need exactly one boundary, so this mode has none.
	const MULTI_SOURCE = 'fc-multi';
	const MULTI_FILL = 'fc-multi-fill';
	const MULTI_CASING = 'fc-multi-casing';
	const MULTI_LINE = 'fc-multi-line';
	// Sorted ids of the selection the multi source was built for
	let multiKeyOnMap: string | null = null;

	/** A paint value per boundary, matched on the fc_id each multi-tile feature carries. */
	function byFc(
		styles: FcStyle[],
		value: (s: FcStyle) => string | number
	): maplibregl.ExpressionSpecification {
		// match labels must be unique
		const unique = [...new Map(styles.map((s) => [s.id, s])).values()];
		const branches = unique.flatMap((s) => [s.id, value(s)]);
		// The spec's tuple type can't describe a variable number of branches
		return ['match', ['get', 'fc_id'], ...branches, value(unique[0])] as unknown as maplibregl.ExpressionSpecification;
	}

	// A selected feature gets a heavier outline, so selection doesn't rest on fill opacity alone (§11)
	const SELECTED_EXTRA_WIDTH = 1.5;
	// Each colored line sits on a forest casing 2px wider, keeping gold and sky lines visible on the light basemap
	const CASING_EXTRA_WIDTH = 2;

	function lineWidth(base: number, extra = 0): maplibregl.ExpressionSpecification {
		return [
			'case',
			['boolean', ['feature-state', 'selected'], false],
			base + extra + SELECTED_EXTRA_WIDTH,
			base + extra
		];
	}

	const ATTRIBUTION =
		'<a href="https://protomaps.com">Protomaps</a> &copy; <a href="https://openstreetmap.org">OpenStreetMap</a> · Features simplified for visualization only';

	onMount(() => {
		let stopTheme: (() => void) | undefined;
		protomapsApiKey().then((key) => {
			map = new maplibregl.Map({
				container: mapContainer,
				style: basemapStyle(get(resolvedTheme), key, ATTRIBUTION),
				center: [0, 20],
				zoom: 2
			});

			map.on('load', () => {
				mapReady = true;
				onZoomChange?.(map!.getZoom());
			});

			stopTheme = followTheme(map, key, () => themeTick++, ATTRIBUTION);

			map.on('zoom', () => {
				onZoomChange?.(map!.getZoom());
			});

			map.on('error', (e) => {
				console.error('MapLibre error:', e.error?.message || e);
			});
		});

		return () => {
			stopTheme?.();
			map?.remove();
		};
	});

	function addFc(m: maplibregl.Map, style: FcStyle) {
		const { name, color, lineWidth: width, bbox: bounds } = style;

		m.addSource(fcSourceId(name), {
			type: 'vector',
			tiles: [boundaryTileUrl(name)],
			minzoom: 0,
			maxzoom: 12,
			promoteId: { [name]: 'id' },
			...(bounds ? { bounds } : {})
		});

		const resolved = resolveColor(color);

		m.addLayer({
			id: fcFillId(name),
			type: 'fill',
			source: fcSourceId(name),
			'source-layer': name,
			paint: {
				'fill-color': resolved,
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
			id: fcCasingId(name),
			type: 'line',
			source: fcSourceId(name),
			'source-layer': name,
			paint: {
				'line-color': readTokens().forest,
				'line-width': lineWidth(width, CASING_EXTRA_WIDTH)
			}
		});

		m.addLayer({
			id: fcLineId(name),
			type: 'line',
			source: fcSourceId(name),
			'source-layer': name,
			paint: {
				'line-color': resolved,
				'line-width': lineWidth(width)
			}
		});
	}

	function removeFc(m: maplibregl.Map, name: string) {
		if (m.getLayer(fcLineId(name))) m.removeLayer(fcLineId(name));
		if (m.getLayer(fcCasingId(name))) m.removeLayer(fcCasingId(name));
		if (m.getLayer(fcFillId(name))) m.removeLayer(fcFillId(name));
		if (m.getSource(fcSourceId(name))) m.removeSource(fcSourceId(name));
	}

	function addMulti(m: maplibregl.Map, styles: FcStyle[], key: string) {
		const bounds = unionBbox(styles.map((s) => s.bbox));

		m.addSource(MULTI_SOURCE, {
			type: 'vector',
			tiles: [multiBoundaryTileUrl(styles.map((s) => s.id))],
			minzoom: 0,
			maxzoom: 12,
			...(bounds ? { bounds } : {})
		});

		const color = byFc(styles, (s) => resolveColor(s.color));

		m.addLayer({
			id: MULTI_FILL,
			type: 'fill',
			source: MULTI_SOURCE,
			'source-layer': MULTI_TILE_LAYER,
			paint: { 'fill-color': color, 'fill-opacity': 0.15 }
		});

		m.addLayer({
			id: MULTI_CASING,
			type: 'line',
			source: MULTI_SOURCE,
			'source-layer': MULTI_TILE_LAYER,
			paint: {
				'line-color': readTokens().forest,
				'line-width': byFc(styles, (s) => s.lineWidth + CASING_EXTRA_WIDTH)
			}
		});

		m.addLayer({
			id: MULTI_LINE,
			type: 'line',
			source: MULTI_SOURCE,
			'source-layer': MULTI_TILE_LAYER,
			paint: {
				'line-color': color,
				'line-width': byFc(styles, (s) => s.lineWidth)
			}
		});

		multiKeyOnMap = key;
	}

	function removeMulti(m: maplibregl.Map) {
		if (m.getLayer(MULTI_LINE)) m.removeLayer(MULTI_LINE);
		if (m.getLayer(MULTI_CASING)) m.removeLayer(MULTI_CASING);
		if (m.getLayer(MULTI_FILL)) m.removeLayer(MULTI_FILL);
		if (m.getSource(MULTI_SOURCE)) m.removeSource(MULTI_SOURCE);
		multiKeyOnMap = null;
	}

	// Sync FC tile sources/layers with the selection: a source per boundary for
	// one boundary, the shared multi source for two or more
	$effect(() => {
		if (!map || !mapReady) return;
		const m = map;
		const styles = [...fcStyles];
		const names = styles.map((s) => s.name);
		const multiKey =
			styles.length >= 2
				? [...new Set(styles.map((s) => s.id))].sort((a, b) => a - b).join(',')
				: null;

		const existingFcNames = Object.keys(m.getStyle()?.sources ?? {})
			.filter((s) => s.startsWith('fc-tiles-'))
			.map((s) => s.slice('fc-tiles-'.length));

		for (const name of existingFcNames) {
			if (multiKey !== null || !names.includes(name)) removeFc(m, name);
		}

		// Rebuilt rather than updated: the tile URL and bounds both follow the selection
		if (m.getSource(MULTI_SOURCE) && multiKey !== multiKeyOnMap) removeMulti(m);

		if (multiKey !== null) {
			if (!m.getSource(MULTI_SOURCE)) addMulti(m, styles, multiKey);
			return;
		}

		for (const style of styles) {
			if (!existingFcNames.includes(style.name)) addFc(m, style);
		}
	});

	// Keep paint props in sync for already-added FCs when their style metadata changes
	// (and re-resolve token colors after a theme change)
	$effect(() => {
		if (!map || !mapReady) return;
		void themeTick;
		const m = map;
		const forest = readTokens().forest;
		for (const style of fcStyles) {
			const color = resolveColor(style.color);
			const fillId = fcFillId(style.name);
			const lineId = fcLineId(style.name);
			const casingId = fcCasingId(style.name);
			if (m.getLayer(fillId)) {
				m.setPaintProperty(fillId, 'fill-color', color);
			}
			if (m.getLayer(casingId)) {
				m.setPaintProperty(casingId, 'line-color', forest);
				m.setPaintProperty(casingId, 'line-width', lineWidth(style.lineWidth, CASING_EXTRA_WIDTH));
			}
			if (m.getLayer(lineId)) {
				m.setPaintProperty(lineId, 'line-color', color);
				m.setPaintProperty(lineId, 'line-width', lineWidth(style.lineWidth));
			}
		}
		if (m.getLayer(MULTI_FILL) && fcStyles.length >= 2) {
			const color = byFc(fcStyles, (s) => resolveColor(s.color));
			m.setPaintProperty(MULTI_FILL, 'fill-color', color);
			m.setPaintProperty(MULTI_CASING, 'line-color', forest);
			m.setPaintProperty(
				MULTI_CASING,
				'line-width',
				byFc(fcStyles, (s) => s.lineWidth + CASING_EXTRA_WIDTH)
			);
			m.setPaintProperty(MULTI_LINE, 'line-color', color);
			m.setPaintProperty(MULTI_LINE, 'line-width', byFc(fcStyles, (s) => s.lineWidth));
		}
		if (m.getLayer(USER_FILL)) m.setPaintProperty(USER_FILL, 'fill-color', readTokens().ring);
		if (m.getLayer(USER_LINE)) m.setPaintProperty(USER_LINE, 'line-color', readTokens().ring);
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
		void themeTick; // a full style reload drops feature state
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
			// Uploaded and edited shapes: a dashed focus-ring line (§11)
			const ring = readTokens().ring;
			m.addLayer({
				id: USER_FILL,
				type: 'fill',
				source: USER_SOURCE,
				paint: { 'fill-color': ring, 'fill-opacity': 0.15 },
			});
			m.addLayer({
				id: USER_LINE,
				type: 'line',
				source: USER_SOURCE,
				paint: { 'line-color': ring, 'line-width': 2, 'line-dasharray': [2, 2] },
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
