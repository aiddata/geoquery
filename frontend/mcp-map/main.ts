import { App, applyDocumentTheme, applyHostFonts, applyHostStyleVariables } from '@modelcontextprotocol/ext-apps';
import { layers, namedFlavor } from '@protomaps/basemaps';
import maplibregl, { type GeoJSONSource, type Map as MapLibreMap } from 'maplibre-gl';

import { equalBreaks, hasSingleTemporalTrack, quantileBreaks } from './map';
import './style.css';

type NumericValue = number | null;
type Column = { name: string; label: string; temporal?: string | null; partial?: boolean };
type AttributionItem = {
	title?: string;
	source_name?: string;
	source_url?: string;
	license?: string;
	license_url?: string;
};
type MapPayload = {
	title?: string;
	viz_url?: string | null;
	columns: Column[];
	column: string | null;
	palette: { name: string; colors: string[] };
	classification: 'quantile' | 'equal';
	classes: number;
	bbox?: [number, number, number, number] | null;
	no_data_color: string;
	basemap: { tiles: string; glyphs: string; sprite: string; attribution: string };
	values: Record<string, Record<string, NumericValue>>;
	geojson?: GeoJSON.FeatureCollection | null;
	feature_count: number;
	truncated: boolean;
	attribution?: { datasets?: AttributionItem[]; boundaries?: AttributionItem[] };
};

const PALETTES: Record<string, string[]> = {
	YlOrRd: ['#ffffb2', '#fecc5c', '#fd8d3c', '#f03b20', '#bd0026'],
	Blues: ['#eff3ff', '#bdd7e7', '#6baed6', '#3182bd', '#08519c'],
	Greens: ['#edf8e9', '#bae4b3', '#74c476', '#31a354', '#006d2c'],
	Purples: ['#f2f0f7', '#cbc9e2', '#9e9ac8', '#756bb1', '#54278f'],
	Oranges: ['#feedde', '#fdbe85', '#fd8d3c', '#e6550d', '#a63603'],
	YlGn: ['#ffffcc', '#c2e699', '#78c679', '#31a354', '#006837'],
	RdYlGn: ['#d7191c', '#fdae61', '#ffffbf', '#a6d96a', '#1a9641'],
	RdBu: ['#ca0020', '#f4a582', '#f7f7f7', '#92c5de', '#0571b0'],
	PuOr: ['#5e3696', '#b2abd2', '#f7f7f7', '#fdb863', '#e66101'],
	BrBG: ['#8c510a', '#d8b365', '#f5f5f5', '#5ab4ac', '#01665e']
};

function element<T extends HTMLElement>(id: string): T {
	const found = document.getElementById(id);
	if (!found) throw new Error(`Missing element #${id}`);
	return found as T;
}

const app = new App({ name: 'GeoQuery map', version: '1.0.0' }, {}, { autoResize: true });
let state: MapPayload | null = null;
let map: MapLibreMap | null = null;
let playTimer: number | null = null;
let hoverInstalled = false;

const fmt = (value: number | null | undefined): string => {
	if (value == null || !Number.isFinite(value)) return '—';
	const absolute = Math.abs(value);
	if (absolute >= 10_000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
	if (absolute >= 100) return value.toFixed(1);
	if (absolute >= 1) return value.toFixed(3);
	return value === 0 ? '0' : value.toPrecision(3);
};

function activeValues(): number[] {
	if (!state?.column) return [];
	return Object.values(state.values[state.column] ?? {}).filter(
		(value): value is number => typeof value === 'number' && Number.isFinite(value)
	);
}

function computeBreaks(): number[] {
	if (!state) return [];
	return state.classification === 'equal'
		? equalBreaks(activeValues(), state.classes)
		: quantileBreaks(activeValues(), state.classes);
}

function getColor(value: NumericValue | undefined, breaks: number[], palette: string[], noData: string): string {
	if (typeof value !== 'number' || !Number.isFinite(value) || !breaks.length) return noData;
	for (let index = 1; index < breaks.length; index += 1) {
		if (value <= breaks[index]) return palette[Math.min(index - 1, palette.length - 1)];
	}
	return palette.at(-1) ?? noData;
}

function renderLegend(breaks: number[], palette: string[]): void {
	const swatches = element<HTMLDivElement>('swatches');
	swatches.replaceChildren(...palette.map((color) => {
		const swatch = document.createElement('i');
		swatch.style.background = color;
		return swatch;
	}));
	element('scale').textContent = breaks.length ? `${fmt(breaks[0])} → ${fmt(breaks.at(-1))}` : 'no numeric values';
	const values = activeValues();
	element('stats').textContent = values.length
		? `n=${values.length.toLocaleString()} · mean ${fmt(values.reduce((sum, value) => sum + value, 0) / values.length)}`
		: '';
}

function paint(): void {
	if (!state || !map?.getLayer('features-fill')) return;
	const breaks = computeBreaks();
	const palette = PALETTES[state.palette.name] ?? state.palette.colors ?? PALETTES.YlOrRd;
	const values = state.column ? state.values[state.column] ?? {} : {};
	const expression: unknown[] = ['match', ['id']];
	let hasValues = false;
	for (const [id, value] of Object.entries(values)) {
		expression.push(Number(id), getColor(value, breaks, palette, state.no_data_color));
		hasValues = true;
	}
	expression.push(state.no_data_color);
	map.setPaintProperty(
		'features-fill',
		'fill-color',
		hasValues ? expression as maplibregl.ExpressionSpecification : state.no_data_color
	);
	renderLegend(breaks, palette);
}

function fitBounds(): void {
	if (!state?.bbox || !map) return;
	const [west, south, east, north] = state.bbox;
	map.fitBounds([[west, south], [east, north]], { padding: 24, maxZoom: 9, duration: 0 });
}

function installHover(): void {
	if (!map || hoverInstalled) return;
	hoverInstalled = true;
	const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
	map.on('mousemove', 'features-fill', (event) => {
		const feature = event.features?.[0];
		if (!feature || !state) return;
		map!.getCanvas().style.cursor = 'pointer';
		const value = state.column ? (state.values[state.column] ?? {})[String(feature.id)] : null;
		const content = document.createElement('div');
		const name = document.createElement('b');
		name.textContent = String(feature.properties?.name ?? feature.id ?? 'Feature');
		content.append(name, document.createTextNode(fmt(value)));
		popup.setLngLat(event.lngLat).setDOMContent(content).addTo(map!);
	});
	map.on('mouseleave', 'features-fill', () => {
		map!.getCanvas().style.cursor = '';
		popup.remove();
	});
}

function updateMap(): void {
	const mapElement = element<HTMLDivElement>('map');
	if (!state?.geojson) {
		mapElement.style.display = 'none';
		return;
	}
	mapElement.style.display = '';
	if (map) {
		const source = map.getSource('features') as GeoJSONSource | undefined;
		source?.setData(state.geojson);
		fitBounds();
		paint();
		map.resize();
		return;
	}

	map = new maplibregl.Map({
		container: mapElement,
		style: {
			version: 8,
			glyphs: state.basemap.glyphs,
			sprite: state.basemap.sprite,
			sources: {
				protomaps: {
					type: 'vector',
					tiles: [state.basemap.tiles],
					maxzoom: 15,
					attribution: state.basemap.attribution
				}
			},
			layers: layers('protomaps', namedFlavor('light'), { lang: 'en' })
		},
		center: [0, 20],
		zoom: 1,
		attributionControl: false
	});
	map.on('load', () => {
		if (!map || !state?.geojson) return;
		map.addSource('features', { type: 'geojson', data: state.geojson });
		map.addLayer({
			id: 'features-fill', type: 'fill', source: 'features',
			paint: { 'fill-color': state.no_data_color, 'fill-opacity': 0.8 }
		});
		map.addLayer({
			id: 'features-line', type: 'line', source: 'features',
			paint: { 'line-color': '#334155', 'line-width': 0.6 }
		});
		fitBounds();
		paint();
		installHover();
	});
}

function setColumn(name: string): void {
	if (!state) return;
	state.column = name;
	element<HTMLSelectElement>('column').value = name;
	const columnNames = JSON.parse(element('yearbar').dataset.columns ?? '[]') as string[];
	const index = columnNames.indexOf(name);
	if (index >= 0) {
		element<HTMLInputElement>('year').value = String(index);
		element('yearlabel').textContent = state.columns.find((column) => column.name === name)?.temporal ?? '';
	}
	paint();
}

function renderControls(): void {
	if (!state) return;
	const columnSelect = element<HTMLSelectElement>('column');
	columnSelect.replaceChildren(...state.columns.map((column) => {
		const option = document.createElement('option');
		option.value = column.name;
		option.selected = column.name === state!.column;
		option.textContent = `${column.label}${column.temporal ? ` · ${column.temporal}` : ''}${column.partial ? ' (partial)' : ''}`;
		return option;
	}));

	const paletteSelect = element<HTMLSelectElement>('palette');
	paletteSelect.replaceChildren(...Object.keys(PALETTES).map((name) => {
		const option = new Option(name, name, false, name === state!.palette.name);
		return option;
	}));
	const methodSelect = element<HTMLSelectElement>('classification');
	methodSelect.replaceChildren(...['quantile', 'equal'].map((name) => new Option(name, name, false, name === state!.classification)));

	const temporal = state.columns.filter((column) => column.temporal);
	const yearbar = element<HTMLDivElement>('yearbar');
	if (hasSingleTemporalTrack(state.columns)) {
		const slider = element<HTMLInputElement>('year');
		slider.max = String(temporal.length - 1);
		const index = Math.max(0, temporal.findIndex((column) => column.name === state!.column));
		slider.value = String(index);
		element('yearlabel').textContent = temporal[index]?.temporal ?? '';
		yearbar.style.display = 'flex';
		yearbar.dataset.columns = JSON.stringify(temporal.map((column) => column.name));
	} else {
		yearbar.style.display = 'none';
		delete yearbar.dataset.columns;
	}
}

function appendLink(parent: HTMLElement, label: string, url?: string | null): void {
	if (!url) {
		parent.append(document.createTextNode(label));
		return;
	}
	const link = document.createElement('a');
	link.href = url;
	link.textContent = label;
	link.rel = 'noopener';
	link.addEventListener('click', (event) => {
		event.preventDefault();
		void app.openLink({ url }).catch(() => undefined);
	});
	parent.append(link);
}

function renderAttribution(): void {
	if (!state) return;
	const footer = element<HTMLElement>('attribution');
	footer.replaceChildren();
	const items = [...(state.attribution?.datasets ?? []), ...(state.attribution?.boundaries ?? [])];
	items.forEach((item, index) => {
		if (index) footer.append(document.createTextNode(' · '));
		footer.append(document.createTextNode(`${item.title ?? 'Data'} — `));
		appendLink(footer, item.source_name ?? item.title ?? 'source', item.source_url);
		footer.append(document.createTextNode(', '));
		appendLink(footer, item.license ?? 'license not recorded', item.license_url);
	});
	if (items.length) footer.append(document.createTextNode(' · '));
	footer.append(document.createTextNode('via '));
	appendLink(footer, 'GeoQuery', state.viz_url);
	footer.append(document.createTextNode(' · Protomaps © OpenStreetMap'));
}

function renderNotice(): void {
	if (!state) return;
	const notice = element<HTMLDivElement>('notice');
	if (!state.geojson) {
		notice.replaceChildren(document.createTextNode(
			state.truncated
				? `This ${state.feature_count.toLocaleString()}-feature selection is too large to draw in chat. `
				: 'This result was requested without boundary geometry. '
		));
		appendLink(notice, 'Open it in GeoQuery.', state.viz_url);
		notice.style.display = 'block';
	} else {
		notice.style.display = 'none';
	}
}

function render(payload: MapPayload): void {
	try {
		if (!payload || !payload.values || !payload.basemap) throw new Error('The map result is missing its display data.');
		state = payload;
		element('title').textContent = state.title ?? 'GeoQuery';
		element('error').style.display = 'none';
		renderControls();
		renderNotice();
		renderAttribution();
		updateMap();
		paint();
	} catch (error) {
		const target = element<HTMLDivElement>('error');
		target.textContent = error instanceof Error ? error.message : String(error);
		target.style.display = 'block';
	}
}

function applyHostContext(context: ReturnType<typeof app.getHostContext>): void {
	if (!context) return;
	if (context.theme) applyDocumentTheme(context.theme);
	if (context.styles?.variables) applyHostStyleVariables(context.styles.variables);
	if (context.styles?.css?.fonts) applyHostFonts(context.styles.css.fonts);
	document.documentElement.dataset.displayMode = context.displayMode ?? 'inline';
	requestAnimationFrame(() => map?.resize());
}

element<HTMLSelectElement>('column').addEventListener('change', (event) => setColumn((event.target as HTMLSelectElement).value));
element<HTMLSelectElement>('palette').addEventListener('change', (event) => {
	if (!state) return;
	const name = (event.target as HTMLSelectElement).value;
	state.palette = { name, colors: PALETTES[name] };
	paint();
});
element<HTMLSelectElement>('classification').addEventListener('change', (event) => {
	if (!state) return;
	state.classification = (event.target as HTMLSelectElement).value as MapPayload['classification'];
	paint();
});
element<HTMLInputElement>('year').addEventListener('input', (event) => {
	const names = JSON.parse(element('yearbar').dataset.columns ?? '[]') as string[];
	const name = names[Number((event.target as HTMLInputElement).value)];
	if (name) setColumn(name);
});
element<HTMLButtonElement>('play').addEventListener('click', () => {
	const button = element<HTMLButtonElement>('play');
	if (playTimer != null) {
		window.clearInterval(playTimer);
		playTimer = null;
		button.textContent = '▶';
		return;
	}
	button.textContent = '⏸';
	playTimer = window.setInterval(() => {
		if (!state) return;
		const names = JSON.parse(element('yearbar').dataset.columns ?? '[]') as string[];
		if (names.length) setColumn(names[(names.indexOf(state.column ?? '') + 1) % names.length]);
	}, 900);
});
element<HTMLButtonElement>('fullscreen').addEventListener('click', () => {
	const mode = app.getHostContext()?.displayMode === 'fullscreen' ? 'inline' : 'fullscreen';
	void app.requestDisplayMode({ mode }).then((result) => {
		document.documentElement.dataset.displayMode = result.mode;
		requestAnimationFrame(() => map?.resize());
	}).catch(() => undefined);
});

app.ontoolresult = (params) => {
	const payload = params._meta?.['geoquery/map'] ?? params.structuredContent;
	if (payload) render(payload as unknown as MapPayload);
};
app.onhostcontextchanged = applyHostContext;

await app.connect();
applyHostContext(app.getHostContext());
