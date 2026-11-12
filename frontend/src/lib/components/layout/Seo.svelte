<script lang="ts">
	import { page } from '$app/state';
	import { SITE_URL, SITE_NAME, DEFAULT_DESCRIPTION } from '#lib/seo.js';

	interface Props {
		/** Page-specific title; " · GeoQuery" is appended. Omit for the home page. */
		title?: string;
		description?: string;
		/** Keep the page out of search indexes (personal, request-specific or beta pages). */
		noindex?: boolean;
	}

	let { title, description = DEFAULT_DESCRIPTION, noindex = false }: Props = $props();

	const fullTitle = $derived(title ? `${title} · GeoQuery` : `${SITE_NAME}: Geospatial Data Extraction`);
	// Always the production URL, so dev and branch deployments count as duplicates
	// of prod rather than competing with it. (page.url.origin can't decide this:
	// the frontend has no ORIGIN set, so behind the proxy it isn't the public host.)
	const canonical = $derived(SITE_URL + page.url.pathname);
</script>

<svelte:head>
	<title>{fullTitle}</title>
	<meta name="description" content={description} />
	{#if !noindex}
		<link rel="canonical" href={canonical} />
	{:else}
		<meta name="robots" content="noindex" />
	{/if}
	<meta property="og:type" content="website" />
	<meta property="og:site_name" content={SITE_NAME} />
	<meta property="og:title" content={fullTitle} />
	<meta property="og:description" content={description} />
	<meta property="og:url" content={canonical} />
	<meta property="og:image" content={SITE_URL + '/og-image.png'} />
	<meta name="twitter:card" content="summary" />
</svelte:head>
