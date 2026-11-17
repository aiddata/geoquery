<script lang="ts" module>
	import type { Map as MlMap } from 'maplibre-gl';
	import type { Bbox as KeptBbox } from '#lib/utils/bbox.js';

	/** Camera moves jump instead of animating when the user asks for reduced motion. */
	function motion(): { animate: boolean } {
		const reduce = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		return { animate: !reduce };
	}

	// One MapLibre map for the page session. When the map page unmounts (going
	// on to Customize or Review), the map's element is parked off screen at
	// the same size instead of the map being removed, and the next MapFrame
	// adopts it: the camera, tiles and layers are as they were left, with
	// nothing to reload or redraw. Parked, MapLibre idles: it renders only
	// when something changes. A page reload starts a new map.
	let kept: { map: MlMap; element: HTMLDivElement; loaded: boolean } | null = null;
	let parking: HTMLDivElement | null = null;
	// The mounted MapFrame's hook for theme changes, which the map follows even
	// while parked
	let onThemeApplied = () => {};

	function park(map: MlMap, element: HTMLDivElement) {
		if (!parking) {
			parking = document.createElement('div');
			parking.setAttribute('aria-hidden', 'true');
			parking.inert = true;
			parking.style.cssText =
				'position: fixed; top: 0; left: -200vw; overflow: hidden; visibility: hidden; pointer-events: none;';
			document.body.appendChild(parking);
		}
		// The size MapLibre last laid the map out at (by the time this runs, the
		// page has already removed the map's old parent, so it can't be
		// measured). Unchanged, the map isn't resized and keeps its pixels.
		const canvas = map.getCanvas();
		parking.style.width = canvas.style.width;
		parking.style.height = canvas.style.height;
		parking.appendChild(element);
	}

	// State that belongs to the map rather than to one MapFrame, so it carries
	// over with it.
	// The extent last zoomed to: the same extent again is not zoomed to again.
	let fittedBbox: KeptBbox | null = null;
	// Sorted ids of the selection the multi source was built for
	let multiKeyOnMap: string | null = null;
	let prevSelectedIds: number[] = [];
	// Cluster ring images: see onRingImageMissing and setRingPalette
	let ringPalette: string[] = [];
	let ringVersion = 0;
	const ringImages = new Set<string>();
</script>

<script lang="ts">
	import { onMount } from 'svelte';
	import * as maplibregl from 'maplibre-gl';
	import '#lib/map/maplibreWorker.js';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { get } from 'svelte/store';
	import {
		boundaryTileUrl,
		CLUSTER_TILE_LAYER,
		multiBoundaryTileUrl,
		MULTI_TILE_LAYER
	} from '#lib/api.js';
	import { unionBbox, type Bbox } from '#lib/utils/bbox.js';
	import { protomapsApiKey } from '#lib/map/protomapsKey.js';
	import { basemapStyle, followTheme } from '#lib/map/basemap.js';
	import { resolvedTheme } from '#lib/stores/theme.js';
	import { readTokens, resolveColor } from '#lib/theme/tokens.js';
	import { escapeHtml } from '#lib/viz.js';
	import type { FeatureCollection } from 'geojson';

	export interface FcStyle {
		id: number;
		name: string;
		/** Extent of the collection; tiles outside it are never requested. */
		bbox: Bbox | null;
		/** A CSS color or `var(--token)`; resolved before it reaches MapLibre. */
		color: string;
		lineWidth: number;
		/** Display name, for the cluster popup; `name` when absent. */
		title?: string | null;
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

	const fcSourceId = (name: string) => `fc-tiles-${name}`;
	const fcFillId = (name: string) => `fc-fill-${name}`;
	const fcLineId = (name: string) => `fc-line-${name}`;
	const fcCasingId = (name: string) => `fc-casing-${name}`;
	const fcClusterId = (name: string) => `fc-cluster-${name}`;
	const fcClusterLabelId = (name: string) => `fc-cluster-label-${name}`;

	// Two or more boundaries share one source: a single tile request per map tile
	// instead of one per boundary, styled per boundary on each feature's fc_id.
	// Hover, click and selection need exactly one boundary, so this mode has none.
	const MULTI_SOURCE = 'fc-multi';
	const MULTI_FILL = 'fc-multi-fill';
	const MULTI_CASING = 'fc-multi-casing';
	const MULTI_LINE = 'fc-multi-line';
	const MULTI_CLUSTER = 'fc-multi-cluster';
	const MULTI_CLUSTER_LABEL = 'fc-multi-cluster-label';

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

	// Where a selection is too large to draw, its tiles carry counted points instead
	// of polygons (CLUSTER_TILE_LAYER), one per spot for all the selected boundaries
	// together: `count` features in all, fc_<id> of them from each boundary. Each is
	// a card-colored disc with the count, ringed in the colors of the boundaries in
	// it, each arc as long as that boundary's share.
	const CLUSTER_FONT = ['Noto Sans Medium'];
	const CLUSTER_RING_WIDTH = 3;
	// Zoom levels a click on a cluster moves in by
	const CLUSTER_CLICK_ZOOM = 2;

	const CLUSTER_TEXT_SIZE = 14;

	// Ring arcs are whole steps of 360 / CLUSTER_RING_STEPS degrees, so the ring
	// images (one per distinct radius and split) stay few. A boundary with any
	// features in the cluster gets at least one step, so it never vanishes from
	// the ring however small its share.
	const CLUSTER_RING_STEPS = 72;
	const RING_IMAGE_PREFIX = 'gq-ring|';

	// No wider than the clusters' spacing (CLUSTER_RADIUS_PX in
	// backend/features/clusters.py), so neighbours seldom overlap.
	const CLUSTER_MAX_RADIUS = 32;

	// Grows with the logarithm of the count, from 14 px for a few features to the
	// maximum at 100k: a cluster of 5 still shows beside one of 50,000. Never
	// narrower than its label needs (9 · 42 · 950 · 1.5k), and whole pixels, since
	// the radius is part of each ring image's id.
	const clusterRadius: maplibregl.ExpressionSpecification = [
		'max',
		['step', ['get', 'count'], 11, 10, 13, 100, 16, 1000, 18],
		[
			'min',
			CLUSTER_MAX_RADIUS,
			['round', ['+', 10, ['*', 4.5, ['log10', ['max', ['get', 'count'], 1]]]]]
		]
	];

	// 950, 1.5k, 30k, 1.2M
	const clusterLabel: maplibregl.ExpressionSpecification = [
		'let',
		'n',
		['get', 'count'],
		[
			'case',
			['>=', ['var', 'n'], 1e6],
			['concat', ['to-string', ['/', ['round', ['/', ['var', 'n'], 1e5]], 10]], 'M'],
			['>=', ['var', 'n'], 1e4],
			['concat', ['to-string', ['round', ['/', ['var', 'n'], 1e3]]], 'k'],
			['>=', ['var', 'n'], 1e3],
			['concat', ['to-string', ['/', ['round', ['/', ['var', 'n'], 1e2]], 10]], 'k'],
			['to-string', ['var', 'n']]
		]
	];

	// The ring images are drawn on demand (onRingImageMissing, as the map's missing
	// image resolver) from these colors,
	// index-aligned with the boundaries the ring expression was built for. A new
	// palette gets a new version in the image ids, so no stale ring is reused.
	// (ringPalette, ringVersion and ringImages are in the module script: they
	// belong to the map, which outlives this component.)

	/**
	 * The ring image id for a cluster: radius, then each selected boundary's arc in
	 * steps, in selection order (0 when it has no features in the cluster).
	 */
	function ringImageId(styles: FcStyle[]): maplibregl.ExpressionSpecification {
		const steps = styles.flatMap((s, i) => {
			const key = `fc_${s.id}`;
			const arc: maplibregl.ExpressionSpecification = [
				'case',
				['has', key],
				[
					'max',
					1,
					['round', ['*', CLUSTER_RING_STEPS, ['/', ['get', key], ['get', 'count']]]]
				],
				0
			];
			return i === 0 ? [['to-string', arc]] : [',', ['to-string', arc]];
		});
		return [
			'concat',
			`${RING_IMAGE_PREFIX}${ringVersion}|`,
			['to-string', clusterRadius],
			'|',
			...steps
		] as unknown as maplibregl.ExpressionSpecification;
	}

	function onRingImageMissing(m: maplibregl.Map, id: string) {
		if (!id.startsWith(RING_IMAGE_PREFIX) || m.hasImage(id)) return;
		const [, , radius, split] = id.split('|');
		const r = Number(radius);
		const steps = split.split(',').map(Number);
		const total = steps.reduce((a, b) => a + b, 0);
		if (!r || !total) return;

		const dpr = window.devicePixelRatio || 1;
		const size = Math.ceil(2 * r * dpr);
		const canvas = document.createElement('canvas');
		canvas.width = canvas.height = size;
		const ctx = canvas.getContext('2d')!;
		ctx.lineWidth = CLUSTER_RING_WIDTH * dpr;
		const center = size / 2;
		const ringRadius = (r - CLUSTER_RING_WIDTH / 2) * dpr;
		let start = -Math.PI / 2; // clockwise from 12 o'clock
		steps.forEach((n, i) => {
			if (!n) return;
			const sweep = (n / total) * 2 * Math.PI;
			ctx.beginPath();
			ctx.strokeStyle = ringPalette[i] ?? readTokens().forest;
			ctx.arc(center, center, ringRadius, start, start + sweep);
			ctx.stroke();
			start += sweep;
		});
		m.addImage(id, ctx.getImageData(0, 0, size, size), { pixelRatio: dpr });
		ringImages.add(id);
	}

	/** Point a cluster label layer at rings in these boundaries' colors. */
	function setRingPalette(m: maplibregl.Map, labelId: string, styles: FcStyle[]) {
		ringPalette = styles.map((s) => resolveColor(s.color));
		ringVersion++;
		for (const id of ringImages) if (m.hasImage(id)) m.removeImage(id);
		ringImages.clear();
		m.setLayoutProperty(labelId, 'icon-image', ringImageId(styles));
	}

	function addClusterLayers(
		m: maplibregl.Map,
		source: string,
		circleId: string,
		labelId: string,
		styles: FcStyle[]
	) {
		const tokens = readTokens();
		m.addLayer({
			id: circleId,
			type: 'circle',
			source,
			'source-layer': CLUSTER_TILE_LAYER,
			paint: {
				'circle-radius': clusterRadius,
				'circle-color': tokens.card,
				'circle-opacity': 0.92
			}
		});
		m.addLayer({
			id: labelId,
			type: 'symbol',
			source,
			'source-layer': CLUSTER_TILE_LAYER,
			layout: {
				'icon-allow-overlap': true,
				'icon-ignore-placement': true,
				'text-field': clusterLabel,
				'text-font': CLUSTER_FONT,
				'text-size': CLUSTER_TEXT_SIZE,
				'text-allow-overlap': true,
				'text-ignore-placement': true
			},
			paint: { 'text-color': tokens.foreground }
		});
		setRingPalette(m, labelId, styles);
	}

	/** Popup body for a cluster: each selected boundary in it, largest first. */
	function clusterPopupHtml(props: Record<string, unknown>, styles: FcStyle[]): string {
		const rows = styles
			.map((s) => ({ style: s, n: Number(props[`fc_${s.id}`] ?? 0) }))
			.filter((row) => row.n > 0)
			.sort((a, b) => b.n - a.n)
			.map(
				({ style, n }) =>
					`<div style="display:flex;align-items:center;gap:6px">` +
					`<span style="width:10px;height:10px;border-radius:9999px;flex:none;background:${resolveColor(style.color)}"></span>` +
					`<span style="flex:1">${escapeHtml(style.title || style.name)}</span>` +
					`<span style="font-variant-numeric:tabular-nums">${n.toLocaleString()}</span>` +
					`</div>`
			)
			.join('');
		const total = Number(props.count ?? 0).toLocaleString();
		return `<strong>${total} features</strong><div style="margin-top:4px;display:grid;gap:2px">${rows}</div>`;
	}

	function removeLayers(m: maplibregl.Map, ...ids: string[]) {
		for (const id of ids) if (m.getLayer(id)) m.removeLayer(id);
	}

	const ATTRIBUTION =
		'<a href="https://protomaps.com" target="_blank" rel="noopener noreferrer">Protomaps</a> &copy; <a href="https://openstreetmap.org" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> · Features simplified for visualization only · <a href="https://docs.geoquery.org/data_documentation/map-disclaimer/" target="_blank" rel="noopener noreferrer">Disclaimer</a>';

	// The world view the map opens on, and returns to on resetView().
	const INITIAL_CENTER: [number, number] = [0, 20];
	const INITIAL_ZOOM = 2;

	onMount(() => {
		let destroyed = false;
		let detach: (() => void) | undefined;

		// Wire the map to this component: its zoom readout, theme hook and ring
		// images, and the effects below (through `map` and `mapReady`).
		function attach(m: maplibregl.Map) {
			const onZoom = () => onZoomChange?.(m.getZoom());
			m.on('zoom', onZoom);
			onThemeApplied = () => themeTick++;
			// Cluster rings are drawn as their images are first needed. A resolver,
			// not a styleimagemissing listener: since MapLibre 6 an image added from
			// the event comes too late for the tile that asked, which then lays out
			// its clusters with no ring.
			m.setMissingStyleImageResolver((id) => onRingImageMissing(m, id));
			map = m;
			const ready = () => {
				if (destroyed) return;
				mapReady = true;
				onZoom();
			};
			if (kept?.loaded) ready();
			else m.once('load', ready);
			detach = () => {
				m.off('zoom', onZoom);
				onThemeApplied = () => {};
			};
		}

		if (kept) {
			mapContainer.appendChild(kept.element);
			attach(kept.map);
		} else {
			protomapsApiKey().then((key) => {
				if (destroyed) return;
				const element = document.createElement('div');
				element.style.cssText = 'width: 100%; height: 100%;';
				mapContainer.appendChild(element);
				const m = new maplibregl.Map({
					container: element,
					style: basemapStyle(get(resolvedTheme), key, ATTRIBUTION),
					center: INITIAL_CENTER,
					zoom: INITIAL_ZOOM,
					// Symbols cut rather than cross-fade as tiles change. A cluster's ring
					// and count are symbols on a disc that cannot fade, so the default
					// 300 ms fade left half-faded rings around discs that had already
					// gone. Map-wide: basemap labels cut too.
					fadeDuration: 0
				});
				const entry = { map: m, element, loaded: false };
				kept = entry;
				m.once('load', () => (entry.loaded = true));
				followTheme(m, key, () => onThemeApplied(), ATTRIBUTION);
				m.on('error', (e) => {
					console.error('MapLibre error:', e.error?.message || e);
				});
				attach(m);
			});
		}

		return () => {
			destroyed = true;
			detach?.();
			if (kept) park(kept.map, kept.element);
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

		addClusterLayers(m, fcSourceId(name), fcClusterId(name), fcClusterLabelId(name), [style]);
	}

	function removeFc(m: maplibregl.Map, name: string) {
		removeLayers(
			m,
			fcClusterLabelId(name),
			fcClusterId(name),
			fcLineId(name),
			fcCasingId(name),
			fcFillId(name)
		);
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

		addClusterLayers(m, MULTI_SOURCE, MULTI_CLUSTER, MULTI_CLUSTER_LABEL, styles);

		multiKeyOnMap = key;
	}

	function removeMulti(m: maplibregl.Map) {
		removeLayers(m, MULTI_CLUSTER_LABEL, MULTI_CLUSTER, MULTI_LINE, MULTI_CASING, MULTI_FILL);
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
			syncClusterPaint(m, fcClusterId(style.name), fcClusterLabelId(style.name), [style]);
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
			syncClusterPaint(m, MULTI_CLUSTER, MULTI_CLUSTER_LABEL, fcStyles);
		}
		if (m.getLayer(USER_FILL)) m.setPaintProperty(USER_FILL, 'fill-color', readTokens().ring);
		if (m.getLayer(USER_LINE)) m.setPaintProperty(USER_LINE, 'line-color', readTokens().ring);
	});

	function syncClusterPaint(
		m: maplibregl.Map,
		circleId: string,
		labelId: string,
		styles: FcStyle[]
	) {
		if (!m.getLayer(circleId)) return;
		const tokens = readTokens();
		m.setPaintProperty(circleId, 'circle-color', tokens.card);
		m.setPaintProperty(labelId, 'text-color', tokens.foreground);
		setRingPalette(m, labelId, styles);
	}

	// A cluster stands for features too small to pick out here: hovering one lists
	// its boundaries' counts, and clicking zooms in toward where they become polygons
	$effect(() => {
		if (!map || !mapReady) return;
		const m = map;
		const layers = fcNames.length >= 2 ? [MULTI_CLUSTER] : fcNames.map(fcClusterId);
		let clusterPopup: maplibregl.Popup | null = null;

		const onClick = (e: maplibregl.MapLayerMouseEvent) => {
			m.easeTo({ center: e.lngLat, zoom: m.getZoom() + CLUSTER_CLICK_ZOOM, ...motion() });
		};
		const onMove = (e: maplibregl.MapLayerMouseEvent) => {
			const feature = e.features?.[0];
			if (!feature) return;
			m.getCanvas().style.cursor = 'pointer';
			clusterPopup ??= new maplibregl.Popup({ closeButton: false, closeOnClick: false });
			const [lng, lat] = (feature.geometry as GeoJSON.Point).coordinates;
			clusterPopup
				.setLngLat([lng, lat])
				.setHTML(clusterPopupHtml(feature.properties ?? {}, fcStyles))
				.addTo(m);
		};
		const onLeave = () => {
			m.getCanvas().style.cursor = '';
			clusterPopup?.remove();
		};

		for (const id of layers) {
			m.on('click', id, onClick);
			m.on('mousemove', id, onMove);
			m.on('mouseleave', id, onLeave);
		}
		return () => {
			for (const id of layers) {
				m.off('click', id, onClick);
				m.off('mousemove', id, onMove);
				m.off('mouseleave', id, onLeave);
			}
			clusterPopup?.remove();
		};
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

	// Zoom to bbox when it changes: not when the kept map comes back with the
	// extent it was last zoomed to, so it stays where it was left.
	const sameBbox = (a: Bbox | null, b: Bbox | null) =>
		a === b || (!!a && !!b && a.every((v, i) => v === b[i]));

	$effect(() => {
		if (!map || !mapReady) return;
		if (!bbox) {
			// Cleared: the next extent is new, even if it matches the old one.
			fittedBbox = null;
			return;
		}
		if (sameBbox(bbox, fittedBbox)) return;
		const m = map;
		const target = bbox;
		const [west, south, east, north] = target;
		// Recorded when it happens: a fit still waiting when the map is put away
		// is owed next time.
		const fit = () => {
			fittedBbox = target;
			m.fitBounds(
				[
					[west, south],
					[east, north]
				],
				{ padding: 40, maxZoom: 12, ...motion() }
			);
		};
		// Hidden (a narrow screen showing the panel), the map lays out at a
		// stand-in size; fit once it's shown and has its real one.
		if (m.getContainer().clientWidth > 0) {
			fit();
			return;
		}
		const onResize = () => {
			if (m.getContainer().clientWidth === 0) return;
			m.off('resize', onResize);
			fit();
		};
		m.on('resize', onResize);
		return () => m.off('resize', onResize);
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
		map?.zoomIn(motion());
	}

	export function zoomOut() {
		map?.zoomOut(motion());
	}

	export function resetView() {
		map?.easeTo({ center: INITIAL_CENTER, zoom: INITIAL_ZOOM, ...motion() });
	}
</script>

<div bind:this={mapContainer} class="h-full w-full {className}"></div>
