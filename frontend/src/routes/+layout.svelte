<script lang="ts">
	import { page } from '$app/state';
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';
	import Header from '$lib/components/layout/Header.svelte';
	import Sidebar from '$lib/components/layout/Sidebar.svelte';

	let { children } = $props();

	// TODO: Connect to actual cart store
	let cartCount = $state(0);

	// Only show steps on main workflow pages
	const workflowPaths = ['/', '/search', '/checkout'];
	let showSteps = $derived(
		workflowPaths.some((path) => page.url.pathname === path || page.url.pathname.startsWith(path + '/'))
	);
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<link rel="preconnect" href="https://fonts.googleapis.com" />
	<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
	<link
		href="https://fonts.googleapis.com/css2?family=Lato:ital,wght@0,300;0,400;0,700;1,400&display=swap"
		rel="stylesheet"
	/>
	<title>GeoQuery - AidData</title>
</svelte:head>

<div class="flex min-h-screen flex-col font-sans">
	<Header {cartCount} {showSteps} />

	<main class="flex-1">
		{@render children()}
	</main>

	<Sidebar />
</div>
