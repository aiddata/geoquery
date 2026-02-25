<script lang="ts">
	import { goto } from '$app/navigation';
	import { currentStep } from '$lib/stores/ui';
	import { searchBoundaries, type BoundaryResult } from '$lib/api';
	import GeographySearch from '$lib/components/map/GeographySearch.svelte';
	import ZoomControls from '$lib/components/map/ZoomControls.svelte';
	import MapFrame from '$lib/components/map/MapFrame.svelte';

	$effect(() => {
		currentStep.set('map');
	});

	let featuredBoundaries = $state<BoundaryResult[]>([]);

	$effect(() => {
		searchBoundaries('', 5).then((results) => {
			featuredBoundaries = results;
		});
	});

	let mapFrame: MapFrame;

	let selectedBoundaryName = $state<string | null>(null);
	let selectedBoundaryBbox = $state<[number, number, number, number] | null>(null);

	function handleBoundarySelect(boundary: BoundaryResult | null) {
		if (!boundary) {
			selectedBoundaryName = null;
			selectedBoundaryBbox = null;
			return;
		}
		selectedBoundaryName = boundary.name;
		selectedBoundaryBbox = boundary.bbox;
	}

	function handleProceed(boundary: BoundaryResult) {
		goto(`/customize?boundary=${encodeURIComponent(boundary.name)}`);
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
		<GeographySearch
			{featuredBoundaries}
			onSelect={handleBoundarySelect}
			onProceed={handleProceed}
		/>
	</div>

	<!-- Zoom Controls (overlaid on map) -->
	<div class="absolute right-4 top-4 z-10">
		<ZoomControls onZoomIn={handleZoomIn} onZoomOut={handleZoomOut} />
	</div>

	<!-- Map Frame -->
	<MapFrame
		bind:this={mapFrame}
		class="flex-1"
		boundaryName={selectedBoundaryName}
		boundaryBbox={selectedBoundaryBbox}
	/>
</div>
