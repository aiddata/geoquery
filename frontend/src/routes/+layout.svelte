<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { afterNavigate, onNavigate } from '$app/navigation';
	import { gtagEvent } from '#lib/analytics.js';
	import { initAuth } from '#lib/stores/auth.js';
	import '@fontsource/barlow/400.css';
	import '@fontsource/barlow/400-italic.css';
	import '@fontsource/barlow/700.css';
	import '@fontsource/noto-sans/700.css';
	import './layout.css';
	import favicon from '#lib/assets/favicon.svg';

	onMount(initAuth);

	afterNavigate(({ to }) => {
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
	import Sidebar from '#lib/components/layout/Sidebar.svelte';
	import StatusBanner from '#lib/components/layout/StatusBanner.svelte';
	import SupportBanner from '#lib/components/layout/SupportBanner.svelte';
	import { TooltipProvider } from '#lib/components/ui/tooltip/index.js';
	let { children } = $props();

	// Only show steps on main workflow pages
	const workflowPaths = ['/', '/customize', '/review'];
	let showSteps = $derived(
		workflowPaths.some((path) => page.url.pathname === path || page.url.pathname.startsWith(path + '/'))
	);
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<TooltipProvider>
	<!-- data-detail: a step's detail view is open on a narrow screen (lib/stepDetail.ts) -->
	<div class="flex min-h-screen flex-col" data-detail={page.state.detail ? 'open' : 'closed'}>
		<StatusBanner />
		<Header {showSteps} />

		<main class="flex-1">
			{@render children()}
		</main>

		<Sidebar />
		<SupportBanner />
	</div>
</TooltipProvider>
