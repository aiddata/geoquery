<script lang="ts">
	import { customBoundary, type Operation, type OperationType } from '$lib/stores/customBoundary';
	import { Button } from '$lib/components/ui/button';
	import * as Collapsible from '$lib/components/ui/collapsible';
	import * as Select from '$lib/components/ui/select';
	import * as Alert from '$lib/components/ui/alert';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { ChevronDown, Trash2, RefreshCw, Save, ArrowRight, TriangleAlert } from '@lucide/svelte';
	import { tick } from 'svelte';
	import type { FeatureCollection, Feature, Polygon, MultiPolygon } from 'geojson';

	// Intermediate result cache, keyed by the cumulative chain of op ids.
	// Lets append/remove/tweak cycles reuse prior work instead of recomputing
	// every operation from the original upload on each Apply.
	const intermediateCache = new Map<string, FeatureCollection>();
	let cachedOriginal: FeatureCollection | null = null;

	function prefixKey(ops: Operation[], upTo: number): string {
		return ops.slice(0, upTo).map((o) => o.id).join('|');
	}

	interface Props {
		onSave: () => void;
		onBack: () => void;
	}
	let { onSave, onBack }: Props = $props();

	// ── Operation form state ─────────────────────────────────────────────────────
	let addType = $state<OperationType>('buffer');
	let bufferDistance = $state(10);
	let bufferUnits = $state<'kilometers' | 'miles' | 'meters'>('kilometers');

	const typeLabels: Record<OperationType, string> = {
		buffer: 'Buffer',
		simplify: 'Simplify',
		union: 'Union (merge all polygons)'
	};
	const unitLabels = { kilometers: 'Kilometers', miles: 'Miles', meters: 'Meters' } as const;
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
		applying = true;
		applyError = '';
		await tick();
		await new Promise((resolve) => setTimeout(resolve, 0)); // yield to browser paint before turf blocks thread

		const { default: buffer } = await import('@turf/buffer');
		const { default: simplify } = await import('@turf/simplify');
		const { union } = await import('@turf/union');
		const { featureCollection } = await import('@turf/helpers');

		try {
			const ops = $customBoundary.operations;
			const original = $customBoundary.originalFeatures!;

			// Invalidate cache when the underlying upload changes
			if (cachedOriginal !== original) {
				intermediateCache.clear();
				cachedOriginal = original;
			}

			// Find the longest cached prefix and resume from there
			let result: FeatureCollection = original;
			let startIdx = 0;
			for (let i = ops.length; i > 0; i--) {
				const cached = intermediateCache.get(prefixKey(ops, i));
				if (cached) {
					result = cached;
					startIdx = i;
					break;
				}
			}

			for (let i = startIdx; i < ops.length; i++) {
				const op = ops[i];
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
				intermediateCache.set(prefixKey(ops, i + 1), result);
			}

			customBoundary.setFinalFeatures(result);
		} catch (err: unknown) {
			applyError = err instanceof Error ? err.message : 'Operation failed.';
		} finally {
			applying = false;
		}
	}
</script>

<div class="card-surface">
	<div class="flex items-center justify-between border-b px-4 py-3">
		<p class="text-sm font-bold">Edit Boundary</p>
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
			<span class="truncate font-bold">{$customBoundary.fileName}</span>
			<span class="ml-2 shrink-0 text-muted-foreground">
				{$customBoundary.featureCount} feature{$customBoundary.featureCount === 1 ? '' : 's'}
			</span>
		</div>

		<!-- Applied operations list -->
		{#if $customBoundary.operations.length > 0}
			<div class="space-y-1">
				<p class="text-xs font-bold text-muted-foreground">Applied operations (in order)</p>
				{#each $customBoundary.operations as op, i (op.id)}
					<Collapsible.Root>
						<div class="flex items-center gap-2 rounded-md border bg-background px-3 py-1.5">
							<span class="text-xs text-muted-foreground w-4 shrink-0">{i + 1}.</span>
							<span class="flex-1 text-xs font-bold">{operationLabel[op.type]}</span>
							<Collapsible.Trigger>
								{#snippet child({ props })}
									<Button {...props} variant="ghost" size="icon-sm" class="size-7 text-muted-foreground" aria-label="Show details">
										<ChevronDown />
									</Button>
								{/snippet}
							</Collapsible.Trigger>
							<Button
								variant="ghost"
								size="icon-sm"
								onclick={() => customBoundary.removeOperation(op.id)}
								class="size-7 text-muted-foreground hover:text-destructive"
								aria-label="Remove {operationLabel[op.type]}"
							>
								<Trash2 />
							</Button>
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
		<div class="space-y-2 rounded-md bg-muted p-3">
			<p class="text-sm font-bold" id="add-operation-label">Add operation</p>

			<Select.Root type="single" value={addType} onValueChange={(v) => (addType = v as OperationType)}>
				<Select.Trigger size="sm" class="w-full" aria-labelledby="add-operation-label">
					{typeLabels[addType]}
				</Select.Trigger>
				<Select.Content>
					{#each Object.entries(typeLabels) as [value, label] (value)}
						<Select.Item {value} {label} />
					{/each}
				</Select.Content>
			</Select.Root>

			{#if addType === 'buffer'}
				<div class="flex gap-2">
					<Input
						type="number"
						bind:value={bufferDistance}
						min="0.001"
						step="1"
						aria-label="Buffer distance"
						class="min-h-8 w-24"
					/>
					<Select.Root type="single" value={bufferUnits} onValueChange={(v) => (bufferUnits = v as typeof bufferUnits)}>
						<Select.Trigger size="sm" class="flex-1" aria-label="Buffer units">
							{unitLabels[bufferUnits]}
						</Select.Trigger>
						<Select.Content>
							{#each Object.entries(unitLabels) as [value, label] (value)}
								<Select.Item {value} {label} />
							{/each}
						</Select.Content>
					</Select.Root>
				</div>
			{:else if addType === 'simplify'}
				<div class="space-y-1">
					<div class="flex items-center justify-between">
						<Label for="simplify-tolerance" class="text-sm">Tolerance</Label>
						<span class="font-ui text-xs font-bold tabular-nums">{simplifyTolerance}</span>
					</div>
					<input
						id="simplify-tolerance"
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
			<Alert.Root variant="destructive">
				<TriangleAlert />
				<Alert.Description>{applyError}</Alert.Description>
			</Alert.Root>
		{/if}

		<!-- Action bar -->
		<div class="flex gap-2 pt-1">
			<Button
				size="sm"
				variant="outline"
				class="gap-1"
				disabled={applying}
				onclick={() => customBoundary.clearOperations()}
			>
				<RefreshCw />
				Reset
			</Button>
			<Button
				size="sm"
				variant="outline"
				class="flex-1 gap-1"
				disabled={applying}
				onclick={applyOperations}
			>
				{#if applying}
					<span class="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
					Applying…
				{:else}
					Apply &amp; Preview
				{/if}
			</Button>
		</div>

		<Button class="w-full gap-1" disabled={applying} onclick={async () => { if ($customBoundary.needsApply) await applyOperations(); onSave(); }}>
			{#if applying}
				<span class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
				Applying…
			{:else}
				<Save />
				Save Boundary
				<ArrowRight />
			{/if}
		</Button>

	</div>
</div>
