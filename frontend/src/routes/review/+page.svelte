<script lang="ts">
	import Seo from '#lib/components/layout/Seo.svelte';
	import { goto } from '$app/navigation';
	import { currentStep } from '#lib/stores/ui.js';
	import { cart, cartCount } from '#lib/stores/cart.js';
	import { selection, selectionSummary } from '#lib/stores/selection.js';
	import { customBoundary } from '#lib/stores/customBoundary.js';
	import { fetchFeatureIds, submitRequest, type SubmittedRequest, type CustomBoundaryPayload } from '#lib/api.js';
	import { auth } from '#lib/stores/auth.js';
	import { gtagEvent } from '#lib/analytics.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { Separator } from '#lib/components/ui/separator/index.js';
	import * as Card from '#lib/components/ui/card/index.js';
	import * as Collapsible from '#lib/components/ui/collapsible/index.js';
	import * as Alert from '#lib/components/ui/alert/index.js';
	import { Checkbox } from '#lib/components/ui/checkbox/index.js';
	import { ChevronLeft, ChevronRight, ChevronDown, Pencil, Trash2, Send, CheckCircle, CircleAlert, TriangleAlert } from '@lucide/svelte';
	import { formatKwargs } from '#lib/utils.js';

	$effect(() => {
		currentStep.set('review');
	});

	// Multi-boundary selections list every collection; past this many, the rest
	// sit behind a "Show all" toggle. (One extra is shown rather than hidden.)
	const BOUNDARY_PREVIEW = 5;
	let showAllBoundaries = $state(false);
	const selectedFcs = $derived($selection?.mode === 'multi' ? $selection.fcs : []);
	const boundariesCollapsible = $derived(selectedFcs.length > BOUNDARY_PREVIEW + 1);
	const visibleFcs = $derived(
		boundariesCollapsible && !showAllBoundaries ? selectedFcs.slice(0, BOUNDARY_PREVIEW) : selectedFcs
	);

	// Per-set area counts, so a multi-set selection reads as a stack of sets
	// (16 + 260 = 276 rows), not an intersection. The store only keeps the
	// combined id list, so each set is counted on its own; the counts are a
	// nicety, and the card falls back to the combined total without them.
	let fcCounts = $state<Record<number, number>>({});
	$effect(() => {
		const fcs = selectedFcs;
		if (fcs.length < 2) return;
		let cancelled = false;
		Promise.all(fcs.map(async (fc) => [fc.id, (await fetchFeatureIds([fc.id])).length] as const))
			.then((entries) => {
				if (!cancelled) fcCounts = Object.fromEntries(entries);
			})
			.catch(() => {});
		return () => {
			cancelled = true;
		};
	});
	const rowTotal = $derived(
		selectedFcs.length > 1 && selectedFcs.every((fc) => fc.id in fcCounts)
			? selectedFcs.reduce((n, fc) => n + fcCounts[fc.id], 0)
			: null
	);
	const areas = (n: number) => `${n.toLocaleString()} area${n === 1 ? '' : 's'}`;

	// Redirect only if the cart was already empty on arrival (e.g. direct URL access).
	// If the user empties it themselves, let them stay.
	const arrivedEmpty = $cartCount === 0;
	$effect(() => {
		if (arrivedEmpty && $cartCount === 0 && !submitted) {
			goto('/');
		}
	});

	let requestName = $state(`Request ${new Date().toLocaleDateString()} ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`);
	let email = $state('');

	// Signed-in users submit under their account email so the request is
	// linked to their account; anonymous users type an email as before.
	let isSignedIn = $derived($auth.status === 'authenticated');
	$effect(() => {
		if ($auth.status === 'authenticated') {
			email = $auth.user.email;
		}
	});

	let submitting = $state(false);
	let submitError = $state<string | null>(null);
	let submitted = $state<SubmittedRequest | null>(null);
	let boundaryConsent = $state(false);

	let resolvedFeatureIds = $derived($selection?.resolvedFeatureIds ?? []);
	let isCustomMode = $derived($customBoundary.saved && $customBoundary.active);
	let canSubmit = $derived(
		requestName.trim() !== '' &&
		/^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test(email) &&
		$cartCount > 0 &&
		(resolvedFeatureIds.length > 0 || isCustomMode) &&
		(!isCustomMode || boundaryConsent) &&
		!submitting
	);

	function formatResources(resources: string[], labels?: string[]): string {
		const display = labels ?? resources;
		const nums = display.map((r) => {
			const n = parseInt(r);
			return String(n) === r.trim() ? n : NaN;
		});
		if (nums.some((n) => isNaN(n))) return display.slice().sort().join(', ');

		const sorted = nums.slice().sort((a, b) => a - b);
		const groups: number[][] = [[sorted[0]]];
		for (let i = 1; i < sorted.length; i++) {
			const last = groups[groups.length - 1];
			if (sorted[i] === last[last.length - 1] + 1) last.push(sorted[i]);
			else groups.push([sorted[i]]);
		}
		return groups
			.map((g) => (g.length > 2 ? `${g[0]}-${g[g.length - 1]}` : g.join(', ')))
			.join(', ');
	}

	function formatOperation(op: { type: string; params: Record<string, unknown> }): string {
		if (op.type === 'buffer') {
			const d = op.params.distance ?? '';
			const u = op.params.units ?? 'km';
			return `Buffer — ${d} ${u}`;
		}
		if (op.type === 'simplify') {
			const t = op.params.tolerance ?? '';
			return `Simplify — tolerance ${t}°`;
		}
		if (op.type === 'union') return 'Union features';
		return op.type;
	}

	function customizeUrl(): string {
		if (isCustomMode) return '/customize';
		if ($selection?.mode === 'single') return '/customize?selection';
		if ($selection?.mode === 'multi') {
			return `/customize?fc=${$selection.fcs.map((fc) => fc.id).join(',')}`;
		}
		return '/';
	}

	async function handleSubmit() {
		if (!canSubmit) return;
		submitting = true;
		submitError = null;

		try {
			const customBoundaryPayload: CustomBoundaryPayload | undefined = isCustomMode && $customBoundary.finalFeatures
				? {
					features: $customBoundary.finalFeatures,
					operations: $customBoundary.operations,
					fileName: $customBoundary.fileName,
					featureCount: $customBoundary.featureCount,
				}
				: undefined;

			const result = await submitRequest({
				name: requestName,
				email,
				selectionLabel: isCustomMode ? $customBoundary.fileName : $selectionSummary?.label,
				selectionDetail: isCustomMode
					? `Custom upload · ${$customBoundary.featureCount} features`
					: $selectionSummary?.detail,
				featureIds: resolvedFeatureIds,
				customBoundary: customBoundaryPayload,
				datasets: $cart.map((item) => ({
					datasetName: item.datasetName,
					datasetType: item.datasetType,
					extractTypes: item.extractTypes,
					resources: item.resources,
					resourceLabels: item.resourceLabels,
					kwargs: item.kwargs,
				}))
			});
			submitted = result;
			gtagEvent('request_submitted', {
				boundary_type: isCustomMode ? 'custom' : 'standard',
				dataset_count: $cart.length,
				feature_count: isCustomMode ? $customBoundary.featureCount : resolvedFeatureIds.length,
			});
			cart.clear();
			selection.clear();
			customBoundary.reset();
		} catch (err) {
			submitError = err instanceof Error ? err.message : 'Submission failed. Please try again.';
		} finally {
			submitting = false;
		}
	}
</script>

<Seo title="Review Request" noindex />

<div class="flex h-[calc(100vh-8rem)] flex-col">
	<!-- Top bar -->
	<div class="flex items-center gap-3 border-b bg-muted/30 px-4 py-2">
		{#if !submitted}
			<Button variant="ghost" size="sm" onclick={() => history.back()}>
				<ChevronLeft />
				Back
			</Button>
			<span class="text-sm text-muted-foreground">|</span>
			<span class="text-sm">
				Review &amp; Submit ({$cartCount}
				{$cartCount === 1 ? 'dataset' : 'datasets'})
			</span>
		{:else}
			<span class="text-sm font-bold">Request Submitted</span>
		{/if}
	</div>

	<!-- Success state -->
	{#if submitted}
		<div class="flex flex-1 items-center justify-center p-8">
			<div class="max-w-md space-y-4 text-center">
				<CheckCircle class="mx-auto size-12 text-success-text" aria-hidden="true" />
				<h2 class="text-h3">Request Submitted!</h2>
				<p class="text-muted-foreground">
					Your request has been queued. We'll send a download link to
					<strong>{email}</strong> when your data is ready.
				</p>
				{#if submitted.warnings && submitted.warnings.length > 0}
					<Alert.Root variant="warning" class="text-left">
						<TriangleAlert />
						<Alert.Title>Some items could not be added:</Alert.Title>
						<Alert.Description>
							<ul class="mt-1 list-inside list-disc space-y-0.5">
								{#each submitted.warnings as w}
									<li>{w}</li>
								{/each}
							</ul>
						</Alert.Description>
					</Alert.Root>
				{/if}
				<p class="text-xs text-muted-foreground">Request ID: <span class="font-ui font-bold">{submitted.id}</span></p>
				<div class="flex flex-col gap-2 sm:flex-row sm:justify-center">
					<Button href="/requests/{submitted.id}">View Request</Button>
					<Button variant="outline" onclick={() => goto('/')}>Start a New Request</Button>
				</div>
			</div>
		</div>
	{:else}

	<!-- Two-panel layout -->
	<div class="flex flex-1 flex-col overflow-auto md:flex-row md:overflow-hidden">
		<!-- Left: Selections list -->
		<div class="flex-1 overflow-auto p-4 md:p-6">
			<div class="mx-auto max-w-2xl space-y-4">

				{#if isCustomMode}
					<Card.Root class="bg-muted/40">
						<Card.Header class="pb-3">
							<div class="flex items-start justify-between gap-2">
								<div class="min-w-0 flex-1 cursor-default">
									<p class="text-xs font-bold text-muted-foreground">Custom Boundary</p>
									<p class="mt-1 truncate font-bold">{$customBoundary.fileName}</p>
									<p class="text-sm text-muted-foreground">
										{$customBoundary.featureCount} feature{$customBoundary.featureCount === 1 ? '' : 's'}
									</p>
									{#if $customBoundary.operations.length > 0}
										<div class="mt-2">
											<p class="text-xs font-bold text-muted-foreground">
												Operations applied ({$customBoundary.operations.length})
											</p>
											<ol class="mt-1 space-y-0.5 pl-4 text-xs text-muted-foreground list-decimal">
												{#each $customBoundary.operations as op}
													<li>{formatOperation(op)}</li>
												{/each}
											</ol>
										</div>
									{/if}
								</div>
								<Button variant="outline" size="sm" onclick={() => goto('/')}>
									<Pencil />
									Change
								</Button>
							</div>
						</Card.Header>
					</Card.Root>
				{:else if $selectionSummary}
					<Card.Root class="bg-muted/40">
						<Card.Header class="pb-3">
							<div class="min-w-0 flex items-start justify-between gap-2">
								<div class="min-w-0 flex-1 cursor-default">
									<p class="text-xs font-bold text-muted-foreground">Geographic Selection</p>
									{#if selectedFcs.length > 1}
										<ul id="review-boundary-list" class="mt-1 space-y-0.5 font-bold">
											{#each visibleFcs as fc (fc.id)}
												<li class="break-words">
													{fc.title ?? fc.name}{#if fc.id in fcCounts}<span class="ml-1 font-normal text-muted-foreground">· {areas(fcCounts[fc.id])}</span>{/if}
												</li>
											{/each}
										</ul>
										{#if boundariesCollapsible}
											<Button
												variant="ghost"
												size="sm"
												class="mt-1 -ml-2 text-muted-foreground"
												aria-expanded={showAllBoundaries}
												aria-controls="review-boundary-list"
												onclick={() => (showAllBoundaries = !showAllBoundaries)}
											>
												<ChevronDown class="transition-transform {showAllBoundaries ? 'rotate-180' : ''}" />
												{showAllBoundaries ? 'Show fewer' : `Show all ${selectedFcs.length}`}
											</Button>
										{/if}
									{:else}
										<p class="mt-1 break-words font-bold">{$selectionSummary.label}</p>
									{/if}
									<p class="text-sm text-muted-foreground">{$selectionSummary.detail}</p>
									{#if rowTotal !== null}
										<p class="mt-0.5 text-xs text-muted-foreground">
											{rowTotal.toLocaleString()} row{rowTotal === 1 ? '' : 's'} in your results: one for each
											area in each set. Overlapping sets are kept separate, not combined.
										</p>
									{:else if resolvedFeatureIds.length > 0}
										<p class="mt-0.5 text-xs text-muted-foreground">
											{resolvedFeatureIds.length} feature{resolvedFeatureIds.length === 1 ? '' : 's'} total
										</p>
									{/if}
								</div>
								<Button variant="outline" size="sm" onclick={() => goto('/')}>
									<Pencil />
									Change
								</Button>
							</div>
						</Card.Header>
					</Card.Root>
				{/if}

				<div class="flex items-center justify-between">
					<h2 class="text-h4">Your Selections</h2>
					<Button variant="outline" size="sm" onclick={() => goto(customizeUrl())}>
						Add Another Dataset
					</Button>
				</div>

				{#if $cartCount === 0}
					<div class="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
						No datasets selected.
						<button class="underline hover:text-foreground" onclick={() => goto(customizeUrl())}>
							Add a dataset
						</button>
						to continue.
					</div>
				{/if}

				{#each $cart as item, i}
					<Card.Root>
						<Card.Header class="pb-3">
							<div class="min-w-0 flex items-center gap-3">
								<Collapsible.Root class="min-w-0 flex-1">
									<div class="min-w-0 flex items-center gap-3">
										<Collapsible.Trigger>
											{#snippet child({ props })}
												<Button {...props} variant="ghost" size="icon-sm" class="text-muted-foreground" aria-label="Show details">
													<ChevronRight class="transition-transform [[data-state=open]_&]:rotate-90" />
												</Button>
											{/snippet}
										</Collapsible.Trigger>
										<label for="review-item-name-{i}" class="sr-only">Selection name</label>
										<Input
											id="review-item-name-{i}"
											type="text"
											value={item.customName}
											oninput={(e) =>
												cart.updateItemName(i, (e.target as HTMLInputElement).value)}
											class="flex-1 font-bold"
										/>
										<Button
											variant="ghost"
											size="icon-sm"
											onclick={() => cart.removeItem(i)}
											class="text-muted-foreground hover:text-destructive"
											aria-label="Remove {item.customName || item.datasetTitle}"
										>
											<Trash2 />
										</Button>
									</div>

									<Collapsible.Content class="mt-3 space-y-1 pl-7 text-sm text-muted-foreground">
										<p><span class="font-bold">Dataset:</span> {item.datasetTitle}</p>
										<p><span class="font-bold">Type:</span> {item.datasetType}</p>
										{#if item.extractTypes && item.extractTypes.length > 0}
											<p>
												<span class="font-bold">Extract types:</span>
												{item.extractTypes.join(', ')}
											</p>
										{/if}
										{#if item.resources && item.resources.length > 0}
											<p>
												<span class="font-bold">Time periods:</span>
												{formatResources(item.resources, item.resourceLabels)}
											</p>
										{/if}
										{#if item.kwargs}
											<p>
												<span class="font-bold">Filters:</span>
												{formatKwargs(item.kwargs)}
											</p>
										{/if}
								</Collapsible.Content>
								</Collapsible.Root>
							</div>
						</Card.Header>
					</Card.Root>
				{/each}
			</div>
		</div>

		<!-- Right: Submit form -->
		<div class="shrink-0 overflow-auto border-t bg-card p-4 md:w-96 md:border-l md:border-t-0 md:p-6">
			<h2 class="text-h4">Review &amp; Submit</h2>
			<Separator class="my-4" />

			<div class="space-y-4">
				<div class="space-y-2">
					<Label for="request-name">Request Name</Label>
					<Input
						id="request-name"
						bind:value={requestName}
						placeholder="My data request"
					/>
				</div>

				<div class="space-y-2">
					<Label for="email">Email</Label>
					<Input
						id="email"
						type="email"
						bind:value={email}
						placeholder="you@example.com"
						disabled={isSignedIn}
					/>
					{#if isSignedIn}
						<p class="text-xs text-muted-foreground">
							Submitting as {email} — this request will be linked to your account.
							Manage addresses in <a href="/account" class="underline">your account</a>.
						</p>
					{:else}
						<p class="text-xs text-muted-foreground">
							We'll send a download link to this address when your data is ready.
						</p>
					{/if}
				</div>

				<Separator />

				<p class="text-xs text-muted-foreground">
					All datasets will be extracted for the same
					{resolvedFeatureIds.length === 0
						? 'feature selection'
						: resolvedFeatureIds.length === 1
							? '1 feature'
							: `${resolvedFeatureIds.length} features`}.
					Actual dataset coverage may vary across selected features.
				</p>

				{#if isCustomMode}
					<Alert.Root variant="warning" role="note" class="p-3">
						<TriangleAlert />
						<Alert.Title>Custom boundary data notice</Alert.Title>
						<Alert.Description class="space-y-3">
						<p>
							Your uploaded boundary data will be stored on GeoQuery's servers and included with your
							request results. Anyone with your request link can view it — results pages are not
							publicly listed, but are not access-controlled beyond the unique request ID URL.
						</p>
						<p>
							Result files are stored on W&amp;M's computing infrastructure and are not publically available but also not protected by  security measures other than standard file system permissions. The uploaded data will not be used for any purpose other than processing your request without your explicit permission.
						</p>
						<div class="flex items-start gap-2">
							<Checkbox id="boundary-consent" bind:checked={boundaryConsent} class="mt-0.5 shrink-0" />
							<label for="boundary-consent" class="cursor-pointer font-bold">I understand, confirm I have permission to upload this data, and consent to my boundary data being stored and shared as described above.</label>
						</div>
						</Alert.Description>
					</Alert.Root>
				{/if}

				{#if submitError}
					<Alert.Root variant="destructive">
						<CircleAlert />
						<Alert.Description>{submitError}</Alert.Description>
					</Alert.Root>
				{/if}

				<Button class="w-full" size="lg" disabled={!canSubmit} onclick={handleSubmit}>
					<Send />
					{submitting ? 'Submitting…' : 'Submit Request'}
				</Button>
			</div>
		</div>
	</div>
	{/if}
</div>
