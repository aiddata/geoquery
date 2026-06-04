<script lang="ts">
	import { customBoundary } from '$lib/stores/customBoundary';
	import { Button } from '$lib/components/ui/button';
	import { Upload, FileCheck, X, ArrowLeft, AlertCircle } from '@lucide/svelte';
	import type { FeatureCollection, Geometry } from 'geojson';

	const MAX_FILE_BYTES = 50 * 1024 * 1024; // 50 MB

	const ALLOWED_GEOMETRY_TYPES = new Set([
		'Point', 'MultiPoint',
		'LineString', 'MultiLineString',
		'Polygon', 'MultiPolygon',
	]);

	let dragOver = $state(false);
	let error = $state('');
	let uploaded = $derived($customBoundary.originalFeatures !== null);

	function validate(raw: string): FeatureCollection {
		let parsed: unknown;
		try {
			parsed = JSON.parse(raw);
		} catch {
			throw new Error('File is not valid JSON.');
		}

		if (typeof parsed !== 'object' || parsed === null) {
			throw new Error('File is not a valid GeoJSON object.');
		}

		const obj = parsed as Record<string, unknown>;

		// Allow a bare Feature — wrap it
		if (obj.type === 'Feature') {
			parsed = { type: 'FeatureCollection', features: [obj] };
			(parsed as Record<string, unknown>);
		}

		if (obj.type !== 'FeatureCollection') {
			throw new Error('GeoJSON must be a FeatureCollection (or a single Feature).');
		}

		const fc = parsed as FeatureCollection;

		if (!Array.isArray(fc.features) || fc.features.length === 0) {
			throw new Error('FeatureCollection has no features.');
		}

		for (const feature of fc.features) {
			if (feature.type !== 'Feature') {
				throw new Error('All items in features array must be of type "Feature".');
			}
			if (!feature.geometry) {
				throw new Error('All features must have a geometry (null geometries are not supported).');
			}
			const geom = feature.geometry as Geometry;
			if (!ALLOWED_GEOMETRY_TYPES.has(geom.type)) {
				throw new Error(
					`Unsupported geometry type "${geom.type}". Only Point, LineString, Polygon, and their Multi-variants are supported.`
				);
			}
		}

		// Coordinate sanity — sample up to 200 features to avoid blocking the thread
		const sample = fc.features.slice(0, 200);
		for (const feature of sample) {
			validateCoordinates(feature.geometry as Geometry);
		}

		// Strip unknown top-level keys (keep type, features, bbox)
		return {
			type: 'FeatureCollection',
			features: fc.features,
			...(fc.bbox ? { bbox: fc.bbox } : {}),
		};
	}

	function validateCoordinates(geom: Geometry) {
		const coords = extractCoordinates(geom);
		for (const [lng, lat] of coords) {
			if (typeof lng !== 'number' || typeof lat !== 'number') {
				throw new Error('Coordinates must be numbers.');
			}
			if (lng < -180 || lng > 180) throw new Error(`Longitude ${lng} is out of range [-180, 180].`);
			if (lat < -90 || lat > 90) throw new Error(`Latitude ${lat} is out of range [-90, 90].`);
		}
	}

	function extractCoordinates(geom: Geometry): [number, number][] {
		switch (geom.type) {
			case 'Point': return [geom.coordinates as [number, number]];
			case 'MultiPoint':
			case 'LineString': return geom.coordinates as [number, number][];
			case 'MultiLineString':
			case 'Polygon': return (geom.coordinates as [number, number][][]).flat();
			case 'MultiPolygon': return (geom.coordinates as [number, number][][][]).flat(2);
			default: return [];
		}
	}

	function processFile(file: File) {
		error = '';

		if (file.size > MAX_FILE_BYTES) {
			error = `File is too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Maximum size is 50 MB.`;
			return;
		}
		if (!file.name.endsWith('.geojson') && !file.name.endsWith('.json')) {
			error = 'Only .geojson or .json files are accepted.';
			return;
		}

		const reader = new FileReader();
		reader.onload = (e) => {
			try {
				const fc = validate(e.target!.result as string);
				customBoundary.setUpload(file.name, fc);
			} catch (err: unknown) {
				error = err instanceof Error ? err.message : 'Unknown validation error.';
			}
		};
		reader.onerror = () => {
			error = 'Failed to read file.';
		};
		reader.readAsText(file);
	}

	function onFileInput(e: Event) {
		const input = e.target as HTMLInputElement;
		if (input.files?.[0]) processFile(input.files[0]);
		input.value = '';
	}

	function onDrop(e: DragEvent) {
		e.preventDefault();
		dragOver = false;
		const file = e.dataTransfer?.files?.[0];
		if (file) processFile(file);
	}
</script>

<div class="rounded-lg border bg-card shadow-lg">
	<!-- Header -->
	<div class="flex items-center justify-between border-b px-4 py-3">
		<p class="font-semibold text-sm">Use My Own Boundary</p>
		<button
			class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
			onclick={() => customBoundary.deactivate()}
		>
			<ArrowLeft class="h-3 w-3" />
			Back to search
		</button>
	</div>

	<div class="p-4 space-y-3">
		{#if !uploaded}
			<!-- Drop zone -->
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div
				role="button"
				tabindex="0"
				class="relative flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors cursor-pointer
					{dragOver ? 'border-primary bg-primary/5' : 'border-muted-foreground/30 hover:border-primary/60 hover:bg-muted/30'}"
				ondragover={(e) => { e.preventDefault(); dragOver = true; }}
				ondragleave={() => (dragOver = false)}
				ondrop={onDrop}
				onclick={() => document.getElementById('geojson-file-input')?.click()}
				onkeydown={(e) => e.key === 'Enter' && document.getElementById('geojson-file-input')?.click()}
			>
				<Upload class="h-8 w-8 text-muted-foreground" />
				<div>
					<p class="text-sm font-medium">Drop a GeoJSON file here</p>
					<p class="text-xs text-muted-foreground">or click to browse</p>
				</div>
				<p class="text-xs text-muted-foreground">.geojson or .json · max 50 MB</p>
			</div>
			<input
				id="geojson-file-input"
				type="file"
				accept=".geojson,.json"
				class="hidden"
				onchange={onFileInput}
			/>

			{#if error}
				<div class="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
					<AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
					<span>{error}</span>
				</div>
			{/if}

		{:else}
			<!-- Upload success state -->
			<div class="flex items-start gap-3 rounded-md border border-green-200 bg-green-50 px-3 py-2.5">
				<FileCheck class="mt-0.5 h-4 w-4 shrink-0 text-green-700" />
				<div class="min-w-0 flex-1">
					<p class="truncate text-sm font-medium text-green-900">{$customBoundary.fileName}</p>
					<p class="text-xs text-green-700">
						{$customBoundary.featureCount} feature{$customBoundary.featureCount === 1 ? '' : 's'} loaded
					</p>
				</div>
				<button
					onclick={() => customBoundary.clearUpload()}
					class="text-green-700 hover:text-green-900"
					aria-label="Remove file"
				>
					<X class="h-4 w-4" />
				</button>
			</div>

			<Button class="w-full" disabled>
				Continue to Operations
				<!-- Enabled in Phase 2 -->
			</Button>

			<p class="text-center text-xs text-muted-foreground">
				Geospatial editing tools coming in the next step.
			</p>
		{/if}
	</div>
</div>
