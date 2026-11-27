<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { afterNavigate, onNavigate } from '$app/navigation';
	import { gtagEvent } from '#lib/analytics.js';
	import { initAuth } from '#lib/stores/auth.js';
	import { syncThemeWithAccount } from '#lib/stores/themeSync.js';
	import { browser } from '$app/env';
	import { persistTabState, restoreTabState } from '#lib/stores/tabState.js';
	import '@fontsource/barlow/400.css';
	import '@fontsource/barlow/400-italic.css';
	import '@fontsource/barlow/700.css';
	import '@fontsource/noto-sans/700.css';
	import './layout.css';
	import favicon from '#lib/assets/favicon.svg';
	import { recordReturn } from '#lib/backNav.js';

	onMount(initAuth);
	// A signed-in user's theme is saved to their account
	onMount(syncThemeWithAccount);

	// The request being built survives a refresh of this tab (GEO-126). Put
	// back before any page reads the stores, then saved on every change.
	if (browser) restoreTabState();
	onMount(persistTabState);

	afterNavigate((navigation) => {
		// Where the Back buttons on Account, Past Requests and Status go
		recordReturn(navigation);
		const { to } = navigation;
		if (to) {
			gtagEvent('page_view', {
				page_path: to.url.pathname + to.url.search,
				page_title: document.title,
			});
		}
	});
	// Moving between the request steps animates (layout.css, "Step
	// transitions"): the panel's sections resize in place, and the main area
	// fades the next step in over the last, or the last out over the previous.
	// Browsers without view transitions just navigate.
	const STEP_PATHS = ['/', '/customize', '/review'];
	onNavigate((navigation) => {
		if (!document.startViewTransition) return;
		const from = STEP_PATHS.indexOf(navigation.from?.url.pathname ?? '');
		const to = STEP_PATHS.indexOf(navigation.to?.url.pathname ?? '');
		if (from < 0 || to < 0 || from === to) return;

		const root = document.documentElement;
		root.dataset.stepDirection = to > from ? 'forward' : 'back';
		return new Promise((resolve) => {
			const transition = document.startViewTransition(async () => {
				resolve();
				await navigation.complete;
			});
			transition.finished.finally(() => delete root.dataset.stepDirection);
		});
	});

	import Header from '#lib/components/layout/Header.svelte';
	import StatusBanner from '#lib/components/layout/StatusBanner.svelte';
	import SupportBanner from '#lib/components/layout/SupportBanner.svelte';
	import { TooltipProvider } from '#lib/components/ui/tooltip/index.js';
	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<TooltipProvider>
	<!-- data-detail: a step's detail view is open on a narrow screen (lib/stepDetail.ts) -->
	<div class="flex min-h-screen flex-col" data-detail={page.state.detail ? 'open' : 'closed'}>
		<!-- First stop for keyboard users: past the header to the page itself -->
		<a
			href="#main-content"
			class="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-card focus:px-4 focus:py-2 focus:font-bold focus:text-foreground focus:shadow-card focus:outline-2 focus:outline-ring"
		>
			Skip to main content
		</a>
		<StatusBanner />
		<Header />

		<main id="main-content" tabindex="-1" class="flex-1 focus:outline-none">
			{@render children()}
		</main>

		<SupportBanner />
	</div>
</TooltipProvider>
