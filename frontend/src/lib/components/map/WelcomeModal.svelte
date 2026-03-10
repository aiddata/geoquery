<script lang="ts">
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Globe, Layers, Download } from '@lucide/svelte';

	let { open = $bindable(true) }: { open: boolean } = $props();
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-xl gap-6 p-8">
		<Dialog.Header class="gap-3">
			<Dialog.Title class="text-2xl">Welcome to GeoQuery</Dialog.Title>
			<Dialog.Description class="text-base">
				Get a simple-to-use file where every row is a unit of analysis and every column is the
				data you want — no special training required.
			</Dialog.Description>
		</Dialog.Header>
		<div class="space-y-5 text-base">
			<div class="flex items-start gap-4">
				<Globe class="text-muted-foreground mt-0.5 size-6 shrink-0" />
				<p>Choose a country and a unit of analysis.</p>
			</div>
			<div class="flex items-start gap-4">
				<Layers class="text-muted-foreground mt-0.5 size-6 shrink-0" />
				<p>
					Select and customize satellite and other spatial datasets from across disciplines.
				</p>
			</div>
			<div class="flex items-start gap-4">
				<Download class="text-muted-foreground mt-0.5 size-6 shrink-0" />
				<p>
					We will email you the data for use in Excel, STATA, R, or your favorite program as
					soon as it is ready — 100% free.
				</p>
			</div>
		</div>
		<Dialog.Footer>
			<Button size="lg" onclick={() => (open = false)}>Get Started</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
