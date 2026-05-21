<script lang="ts">
	import { goto } from '$app/navigation';
	import { currentStep } from '$lib/stores/ui';
	import { cart, cartCount } from '$lib/stores/cart';
	import { submitRequest, type SubmittedRequest } from '$lib/api';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Separator } from '$lib/components/ui/separator';
	import * as Card from '$lib/components/ui/card';
	import * as Collapsible from '$lib/components/ui/collapsible';
	import { ChevronLeft, ChevronRight, Trash2, Send, CheckCircle } from '@lucide/svelte';

	$effect(() => {
		currentStep.set('review');
	});

	// Redirect if cart is empty and we haven't just submitted
	$effect(() => {
		if ($cartCount === 0 && !submitted) {
			goto('/');
		}
	});

	let requestName = $state(`Request ${new Date().toLocaleDateString()} ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`);
	let email = $state('');

	let submitting = $state(false);
	let submitError = $state<string | null>(null);
	let submitted = $state<SubmittedRequest | null>(null);

	let canSubmit = $derived(requestName.trim() !== '' && email.trim() !== '' && $cartCount > 0 && !submitting);

	async function handleSubmit() {
		if (!canSubmit) return;
		submitting = true;
		submitError = null;

		try {
			const result = await submitRequest({
				name: requestName,
				email,
				items: $cart.map((item) => ({
					boundaryName: item.boundaryName,
					datasetName: item.datasetName,
					datasetType: item.datasetType,
					extractTypes: item.extractTypes,
					resources: item.resources,
					filters: item.filters
				}))
			});
			submitted = result;
			cart.clear();
		} catch (err) {
			submitError = err instanceof Error ? err.message : 'Submission failed. Please try again.';
		} finally {
			submitting = false;
		}
	}
</script>

<div class="flex h-[calc(100vh-7rem)] flex-col">
	<!-- Top bar -->
	<div class="flex items-center gap-3 border-b bg-muted/30 px-4 py-2">
		{#if !submitted}
			<Button variant="ghost" size="sm" onclick={() => history.back()}>
				<ChevronLeft class="mr-1 h-4 w-4" />
				Back
			</Button>
			<span class="text-sm text-muted-foreground">|</span>
			<span class="text-sm">
				Review &amp; Submit ({$cartCount}
				{$cartCount === 1 ? 'dataset' : 'datasets'})
			</span>
		{:else}
			<span class="text-sm font-medium">Request Submitted</span>
		{/if}
	</div>

	<!-- Success state -->
	{#if submitted}
		<div class="flex flex-1 items-center justify-center p-8">
			<div class="max-w-md space-y-4 text-center">
				<CheckCircle class="mx-auto h-12 w-12 text-green-500" />
				<h2 class="text-xl font-semibold">Request Submitted!</h2>
				<p class="text-muted-foreground">
					Your request has been queued. We'll send a download link to
					<strong>{email}</strong> when your data is ready.
				</p>
				{#if submitted.warnings && submitted.warnings.length > 0}
					<div class="rounded-md border border-yellow-200 bg-yellow-50 p-3 text-left text-sm text-yellow-800">
						<p class="font-medium">Some items could not be added:</p>
						<ul class="mt-1 list-inside list-disc space-y-0.5">
							{#each submitted.warnings as w}
								<li>{w}</li>
							{/each}
						</ul>
					</div>
				{/if}
				<p class="text-xs text-muted-foreground">Request ID: {submitted.id}</p>
				<Button onclick={() => goto('/')}>Start a New Request</Button>
			</div>
		</div>
	{:else}

	<!-- Two-panel layout -->
	<div class="flex flex-1 overflow-hidden">
		<!-- Left: Selections list -->
		<div class="flex-1 overflow-auto p-6">
			<div class="mx-auto max-w-2xl space-y-4">
				<div class="flex items-center justify-between">
					<h2 class="text-lg font-semibold">Your Selections</h2>
					<Button variant="outline" size="sm" href="/customize">
						Add Another Dataset
					</Button>
				</div>

				{#each $cart as item, i}
					<Card.Root>
						<Card.Header class="pb-3">
							<div class="flex items-center gap-3">
								<Collapsible.Root class="flex-1">
									<div class="flex items-center gap-3">
										<Collapsible.Trigger
											class="flex items-center text-muted-foreground hover:text-foreground"
										>
											<ChevronRight class="h-4 w-4 transition-transform [[data-state=open]_&]:rotate-90" />
										</Collapsible.Trigger>
										<input
											type="text"
											value={item.customName}
											oninput={(e) =>
												cart.updateItemName(i, (e.target as HTMLInputElement).value)}
											class="flex-1 bg-transparent text-sm font-medium outline-none"
										/>
										<button
											onclick={() => cart.removeItem(i)}
											class="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
										>
											<Trash2 class="h-4 w-4" />
										</button>
									</div>

									<Collapsible.Content class="mt-3 space-y-1 pl-7 text-sm text-muted-foreground">
										<p><span class="font-medium">Dataset:</span> {item.datasetTitle}</p>
										<p><span class="font-medium">Boundary:</span> {item.boundaryName}</p>
										<p><span class="font-medium">Type:</span> {item.datasetType}</p>
										{#if item.filters}
											{#each Object.entries(item.filters) as [field, values]}
												<p>
													<span class="font-medium">{field}:</span>
													{values.length > 0 ? values.join(', ') : 'All'}
												</p>
											{/each}
										{/if}
										{#if item.extractTypes && item.extractTypes.length > 0}
											<p>
												<span class="font-medium">Extract types:</span>
												{item.extractTypes.join(', ')}
											</p>
										{/if}
										{#if item.resources && item.resources.length > 0}
											<p>
												<span class="font-medium">Time periods:</span>
												{item.resources.length} selected
											</p>
										{/if}
										<p class="mt-2 italic">{item.summary}</p>
									</Collapsible.Content>
								</Collapsible.Root>
							</div>
						</Card.Header>
					</Card.Root>
				{/each}
			</div>
		</div>

		<!-- Right: Submit form -->
		<div class="w-96 shrink-0 overflow-auto border-l bg-card p-6">
			<h2 class="text-lg font-semibold">Review &amp; Submit</h2>
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
					/>
					<p class="text-xs text-muted-foreground">
						We'll send a download link to this address when your data is ready.
					</p>
				</div>

				<Separator />

				{#if submitError}
					<p class="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
						{submitError}
					</p>
				{/if}

				<Button class="w-full" size="lg" disabled={!canSubmit} onclick={handleSubmit}>
					<Send class="mr-2 h-4 w-4" />
					{submitting ? 'Submitting…' : 'Submit Request'}
				</Button>
			</div>
		</div>
	</div>
	{/if}
</div>
