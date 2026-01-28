<script lang="ts">
	import { onMount } from 'svelte';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';

	interface Props {
		class?: string;
	}

	let { class: className = '' }: Props = $props();

	let mapContainer: HTMLDivElement;
	let map: maplibregl.Map | null = $state(null);

	onMount(() => {
		map = new maplibregl.Map({
			container: mapContainer,
			style: {
				version: 8,
				sources: {
					osm: {
						type: 'raster',
						tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
						tileSize: 256,
						attribution: '&copy; OpenStreetMap contributors'
					}
				},
				layers: [
					{
						id: 'osm',
						type: 'raster',
						source: 'osm'
					}
				]
			},
			center: [0, 20],
			zoom: 2
		});

		return () => {
			map?.remove();
		};
	});

	export function zoomIn() {
		map?.zoomIn();
	}

	export function zoomOut() {
		map?.zoomOut();
	}

	export function getMap() {
		return map;
	}
</script>

<div bind:this={mapContainer} class="h-full w-full {className}"></div>
