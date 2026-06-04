<script lang="ts">
	import { customBoundary, type Operation, type OperationType } from '$lib/stores/customBoundary';
	import { Button } from '$lib/components/ui/button';
	import * as Collapsible from '$lib/components/ui/collapsible';
	import { ChevronDown, Trash2, RefreshCw, Save, ArrowRight, TriangleAlert } from '@lucide/svelte';
	import type { FeatureCollection, Feature, Polygon, MultiPolygon } from 'geojson';

	interface Props {
		onSave: () => void;
		onBack: () => void;
	}
	let { onSave, onBack }: Props = $props();

	// ── Operation form state ─────────────────────────────────────────────────────
	let addType = $state<OperationType>('buffer');
	let bufferDistance = $state(10);
	let bufferUnits = $state<'kilometers' | 'miles' | 'meters'>('kilometers');
	let simplifyTolerance = $state(0.01);
	let applying = $state(false);
	let applyError = $state('');

	const operationLabel: Record<OperationType, string> = {
		buffer: 'Buffer',
		simplify: 'Simplify',
		union: 'Union',
	};

	function summarize(op: Operation): string {
		if (op.type === 'buffer') return `${op.params.distance} ${op.params.units}`;
		if (op.type === 'simplify') return `tolerance ${op.params.tolerance}`;
		return 'merge all features';
	}

	function addOperation() {
		const id = crypto.randomUUID();
		let op: Operation;
		if (addType === 'buffer') {
			op = { id, type: 'buffer', params: { distance: bufferDistance, units: bufferUnits } };
		} else if (addType === 'simplify') {
			op = { id, type: 'simplify', params: { tolerance: simplifyTolerance } };
		} else {
			op = { id, type: 'union', params: {} };
		}
		customBoundary.addOperation(op);
	}

	async function applyOperations() {
		const { default: buffer } = await import('@turf/buffer');
		const { default: simplify } = await import('@turf/simplify');
		const { union } = await import('@turf/union');
		const { featureCollection } = await import('@turf/helpers');

		applying = true;
		applyError = '';
		try {
			const ops = $customBoundary.operations;
			let result: FeatureCollection = $customBoundary.originalFeatures!;

			for (const op of ops) {
				if (op.type === 'buffer') {
					const buffered = buffer(result, op.params.distance as number, {
						units: op.params.units as 'kilometers' | 'miles' | 'meters',
					});
					if (!buffered) throw new Error('Buffer operation produced no output.');
					result = buffered as FeatureCollection;
				} else if (op.type === 'simplify') {
					result = simplify(result, {
						tolerance: op.params.tolerance as number,
						highQuality: false,
						mutate: false,
					}) as FeatureCollection;
				} else if (op.type === 'union') {
					const polygons = result.features.filter(
						(f) => f.geometry?.type === 'Polygon' || f.geometry?.type === 'MultiPolygon'
					) as Feature<Polygon | MultiPolygon>[];
					if (polygons.length === 0) throw new Error('Union requires at least one polygon feature.');
					const unioned = union(featureCollection(polygons));
					if (!unioned) throw new Error('Union operation produced no output.');
					result = featureCollection([unioned]) as FeatureCollection;
				}
			}

			customBoundary.setFinalFeatures(result);
		} catch (err: unknown) {
			applyError = err instanceof Error ? err.message : 'Operation failed.';
		} finally {
			applying = false;
		}
	}
</script>

<div class="rounded-lg border bg-card shadow-lg">
	<div class="flex items-center justify-between border-b px-4 py-3">
		<p class="text-sm font-semibold">Edit Boundary</p>
		<button
			class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
			onclick={onBack}
		>
			← Back to upload
		</button>
	</div>

	<div class="space-y-3 p-4">

		<!-- File summary -->
		<div class="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2 text-xs">
			<span class="truncate font-medium">{$customBoundary.fileName}</span>
			<span class="ml-2 shrink-0 text-muted-foreground">
				{$customBoundary.featureCount} feature{$customBoundary.featureCount === 1 ? '' : 's'}
			</span>
		</div>

		<!-- Applied operations list -->
		{#if $customBoundary.operations.length > 0}
			<div class="space-y-1">
				<p class="text-xs font-medium text-muted-foreground">Applied operations (in order)</p>
				{#each $customBoundary.operations as op, i (op.id)}
					<Collapsible.Root>
						<div class="flex items-center gap-2 rounded-md border bg-background px-3 py-1.5">
							<span class="text-xs text-muted-foreground w-4 shrink-0">{i + 1}.</span>
							<span class="flex-1 text-xs font-medium">{operationLabel[op.type]}</span>
							<Collapsible.Trigger
								class="text-xs text-muted-foreground hover:text-foreground"
							>
								<ChevronDown class="h-3.5 w-3.5" />
							</Collapsible.Trigger>
							<button
								onclick={() => customBoundary.removeOperation(op.id)}
								class="text-muted-foreground hover:text-destructive"
								aria-label="Remove"
							>
								<Trash2 class="h-3.5 w-3.5" />
							</button>
						</div>
						<Collapsible.Content>
							<p class="px-3 pb-1.5 pt-0.5 text-xs text-muted-foreground">
								{summarize(op)}
							</p>
						</Collapsible.Content>
					</Collapsible.Root>
				{/each}
			</div>
		{:else}
			<p class="text-xs text-muted-foreground">
				No operations applied — features will be used as uploaded.
			</p>
		{/if}

		<!-- Add operation form -->
		<div class="space-y-2 rounded-md border bg-muted/30 p-3">
			<p class="text-xs font-medium">Add operation</p>

			<select
				bind:value={addType}
				class="w-full rounded-md border bg-background px-2 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring"
			>
				<option value="buffer">Buffer</option>
				<option value="simplify">Simplify</option>
				<option value="union">Union (merge all polygons)</option>
			</select>

			{#if addType === 'buffer'}
				<div class="flex gap-2">
					<input
						type="number"
						bind:value={bufferDistance}
						min="0.001"
						step="1"
						class="w-24 rounded-md border bg-background px-2 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring"
					/>
					<select
						bind:value={bufferUnits}
						class="flex-1 rounded-md border bg-background px-2 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring"
					>
						<option value="kilometers">Kilometers</option>
						<option value="miles">Miles</option>
						<option value="meters">Meters</option>
					</select>
				</div>
			{:else if addType === 'simplify'}
				<div class="space-y-1">
					<div class="flex items-center justify-between">
						<label class="text-xs text-muted-foreground">Tolerance</label>
						<span class="text-xs font-medium">{simplifyTolerance}</span>
					</div>
					<input
						type="range"
						bind:value={simplifyTolerance}
						min="0.0001"
						max="1"
						step="0.0001"
						class="w-full accent-primary"
					/>
					<p class="text-xs text-muted-foreground">Higher = more simplified</p>
				</div>
			{/if}

			<Button size="sm" variant="outline" class="w-full" onclick={addOperation}>
				Add Operation
			</Button>
		</div>

		{#if applyError}
			<div class="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
				<TriangleAlert class="mt-0.5 h-3.5 w-3.5 shrink-0" />
				{applyError}
			</div>
		{/if}

		<!-- Action bar -->
		<div class="flex gap-2 pt-1">
			<Button
				size="sm"
				variant="outline"
				class="gap-1"
				disabled={false}
				onclick={() => customBoundary.clearOperations()}
			>
				<RefreshCw class="h-3.5 w-3.5" />
				Reset
			</Button>
			<Button
				size="sm"
				variant="outline"
				class="flex-1"
				disabled={applying}
				onclick={applyOperations}
			>
				{applying ? 'Applying…' : 'Apply & Preview'}
			</Button>
		</div>

		<Button class="w-full gap-1" onclick={onSave}>
			<Save class="h-4 w-4" />
			Save Boundary
			<ArrowRight class="h-4 w-4" />
		</Button>

	</div>
</div>
