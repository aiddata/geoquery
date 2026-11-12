<script lang="ts">
	import Seo from '#lib/components/layout/Seo.svelte';
	import { maintenance } from '#lib/config/status.js';
	import { Wrench } from '@lucide/svelte';
	import geoqueryLogo from '#lib/assets/aiddata_geoquery_wordmark.png';
</script>

<Seo title="Down for Maintenance" noindex />

<div class="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-16 text-center">
	<img src={geoqueryLogo} alt="GeoQuery" class="mb-8 h-14 w-auto opacity-80" />

	<div class="mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
		<Wrench class="h-8 w-8 text-muted-foreground" />
	</div>

	<h1 class="mb-3 text-h2 text-foreground">{maintenance.heading}</h1>

	<p class="mb-4 max-w-md text-muted-foreground">{maintenance.message}</p>

	{#if maintenance.estimatedReturn}
		<p class="text-sm text-muted-foreground">
			Expected back: <span class="font-bold text-foreground">{maintenance.estimatedReturn}</span>
		</p>
	{/if}
</div>