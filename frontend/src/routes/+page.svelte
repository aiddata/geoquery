<script lang="ts">
	import { goto } from '$app/navigation';
	import { currentStep } from '$lib/stores/ui';
	import GeographySearch from '$lib/components/map/GeographySearch.svelte';
	import ZoomControls from '$lib/components/map/ZoomControls.svelte';
	import MapFrame from '$lib/components/map/MapFrame.svelte';

	// Set current step on mount
	$effect(() => {
		currentStep.set('map');
	});

	// Mock data - TODO: Load from API
	const boundaries = [
		{ id: '1', name: 'afghanistan', title: 'Afghanistan' },
		{ id: '2', name: 'albania', title: 'Albania' },
		{ id: '3', name: 'algeria', title: 'Algeria' },
		{ id: '4', name: 'angola', title: 'Angola' },
		{ id: '5', name: 'argentina', title: 'Argentina' },
		{ id: '6', name: 'australia', title: 'Australia' },
		{ id: '7', name: 'bangladesh', title: 'Bangladesh' },
		{ id: '8', name: 'brazil', title: 'Brazil' },
		{ id: '9', name: 'cambodia', title: 'Cambodia' },
		{ id: '10', name: 'cameroon', title: 'Cameroon' }
	];

	const featuredBoundaries = boundaries.slice(0, 5);

	let mapFrame: MapFrame;

	function handleBoundarySelect(
		boundary: { id: string; name: string; title: string },
		subboundary?: string
	) {
		const sub = subboundary || 'adm0';
		goto(`/search/${boundary.name}/${sub}`);
	}

	function handleZoomIn() {
		mapFrame?.zoomIn();
	}

	function handleZoomOut() {
		mapFrame?.zoomOut();
	}
</script>

<div class="relative flex h-[calc(100vh-7rem)] flex-col">
	<!-- Geography Search Panel (overlaid on map) -->
	<div class="absolute left-4 top-4 z-10 w-96">
		<GeographySearch {boundaries} {featuredBoundaries} onSelect={handleBoundarySelect} />
	</div>

	<!-- Zoom Controls (overlaid on map) -->
	<div class="absolute right-4 top-4 z-10">
		<ZoomControls onZoomIn={handleZoomIn} onZoomOut={handleZoomOut} />
	</div>

	<!-- Map Frame -->
	<MapFrame bind:this={mapFrame} class="flex-1" />
</div>
