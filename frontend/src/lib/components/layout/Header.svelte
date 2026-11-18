<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import UserMenu from '#lib/components/layout/UserMenu.svelte';
	import ThemeMenu from '#lib/components/layout/ThemeMenu.svelte';
	import { currentStep, type Step } from '#lib/stores/ui.js';
	import { features } from '#lib/stores/features.js';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.js';
	import { ChevronRight, ChevronUp, Map, Menu as MenuIcon } from '@lucide/svelte';
	import aiddataLogo from '#lib/assets/aiddata_logo.svg';
	import aiddataLogoWhite from '#lib/assets/aiddata_logo_white.png';
	import geoqueryText from '#lib/assets/geoquery_text.svg';

	interface Props {
		showSteps?: boolean;
	}

	let { showSteps = true }: Props = $props();

	// Shown as text links on wide screens and in the menu on narrower ones.
	type NavLink = { label: string; href?: string; external?: boolean; onclick?: () => void };
	const navLinks: NavLink[] = [
		{ label: 'About', href: 'https://www.aiddata.org/geoquery', external: true },
		{ label: 'Documentation', href: 'https://docs.geoquery.org/', external: true },
		// The news page: markdown posts in docs/updates/posts/, published with the docs.
		{ label: 'Updates', href: 'https://docs.geoquery.org/updates/', external: true },
		{ label: 'Past Requests', href: '/requests' }
	];

	// Where you are in the request: plain breadcrumbs, not links. The
	// request panel on each step page is the navigation.
	const steps: { id: Step; label: string }[] = [
		{ id: 'map', label: 'Select Boundaries' },
		{ id: 'search', label: 'Customize Datasets' },
		{ id: 'review', label: 'Review & Submit' }
	];

	// Published as --header-height, so the step pages can fill the rest of the
	// screen whatever the header's height (the steps band hides below lg)
	let headerHeight = $state(0);
	$effect(() => {
		if (headerHeight) document.documentElement.style.setProperty('--header-height', `${headerHeight}px`);
	});
</script>

<!-- Small arrow at the top right of a link that opens another site. It takes
     the link's own colour so it reads as part of the label. -->
{#snippet externalMark()}
	<ChevronUp class="-ml-2 -mt-0.5 size-2.5 rotate-[40deg] self-start" stroke-width={3} aria-hidden="true" />
	<span class="sr-only">(opens in a new tab)</span>
{/snippet}

<!-- Heights are multiples of --lh, one line of body text (1.6em at the header's
     17px), so the header keeps its proportions if the base text size changes. -->
<header
	bind:offsetHeight={headerHeight}
	class="sticky top-0 z-50 w-full bg-card shadow-card [--lh:calc(var(--text-base--line-height)*1em)]"
>
	<!-- Main Header -->
	<!-- A size container, so the GeoQuery wordmark can drop out only when the
	     row itself has no room left beside the controls. -->
	<div class="@container flex min-h-[calc(3*var(--lh))] items-center justify-between gap-3 px-4">
		<!-- Logo: AidData's goes first on narrow screens; GeoQuery's stays. -->
		<div class="flex shrink-0 items-center gap-3">
			<!-- AidData's own white-lettered logo for dark mode; the triangles keep their colours. -->
			<a
				href="https://www.aiddata.org/"
				target="_blank"
				rel="noopener noreferrer"
				aria-label="AidData (opens in a new tab)"
				class="hidden md:block"
			>
				<img src={aiddataLogo} alt="" class="h-[calc(1.7*var(--lh))] w-auto dark:hidden" />
				<img src={aiddataLogoWhite} alt="" class="hidden h-[calc(1.7*var(--lh))] w-auto dark:block" />
			</a>
			<span class="hidden h-[calc(1.5*var(--lh))] w-px bg-border md:block" aria-hidden="true"></span>
			<!-- 21.25rem of content box (padding excluded): the ~200px wordmark, the row
			     gap and the three icon-only controls (~128px). -->
			<a href="/" class="hidden @min-[21.25rem]:block" aria-label="GeoQuery home">
				<img src={geoqueryText} alt="" class="h-[calc(1.5*var(--lh))] w-auto brightness-0 dark:invert" />
			</a>
		</div>

		<!-- Navigation Buttons -->
		<div class="flex items-center gap-2">
			<!-- Wide screens (xl+): text links divided by thin rules -->
			<nav aria-label="Main" class="hidden items-center gap-1 xl:flex">
				{#each navLinks as link, i}
					{#if i > 0}
						<span class="h-5 w-px bg-border" aria-hidden="true"></span>
					{/if}
					{#if link.href}
						<Button variant="ghost" href={link.href} target={link.external ? '_blank' : undefined} rel={link.external ? 'noopener noreferrer' : undefined}>
							{link.label}{#if link.external}{@render externalMark()}{/if}
						</Button>
					{:else}
						<Button variant="ghost" onclick={link.onclick}>{link.label}</Button>
					{/if}
				{/each}
			</nav>

			<ThemeMenu />
			<UserMenu />

			<!-- Narrower screens: the same links in a menu -->
			<DropdownMenu.Root>
				<DropdownMenu.Trigger>
					{#snippet child({ props })}
						<Button {...props} variant="ghost" size="icon" class="xl:hidden" aria-label="Menu">
							<MenuIcon />
						</Button>
					{/snippet}
				</DropdownMenu.Trigger>
				<DropdownMenu.Content align="end" class="w-48">
					{#each navLinks as link}
						{#if link.href}
							<DropdownMenu.Item>
								{#snippet child({ props })}
									<a {...props} href={link.href} target={link.external ? '_blank' : undefined} rel={link.external ? 'noopener noreferrer' : undefined}>
										{link.label}{#if link.external}{@render externalMark()}{/if}
									</a>
								{/snippet}
							</DropdownMenu.Item>
						{:else}
							<DropdownMenu.Item onclick={link.onclick}>{link.label}</DropdownMenu.Item>
						{/if}
					{/each}
				</DropdownMenu.Content>
			</DropdownMenu.Root>
		</div>
	</div>

	<!-- Step Indicator (only on workflow pages). Not below lg, where the panel's
	     own step headers are enough and the height is better spent on content. -->
	{#if showSteps}
		<div class="flex min-h-[calc(1.75*var(--lh))] items-center justify-between bg-band px-4 max-lg:hidden">
			<div aria-label="Request progress" class="flex items-center gap-1">
				{#each steps as step, i (step.id)}
					{#if i > 0}
						<ChevronRight class="size-3.5 shrink-0 text-muted-foreground/60" aria-hidden="true" />
					{/if}
					<span
						class="px-1 text-xs {$currentStep === step.id ? 'font-bold text-foreground' : 'text-muted-foreground'}"
						aria-current={$currentStep === step.id ? 'step' : undefined}
					>
						{step.label}
					</span>
				{/each}
			</div>

			{#if $features.has('visualize')}
				<Button
					variant="ghost"
					size="sm"
					href="/viz/explore"
					class="hidden font-body text-muted-foreground lg:inline-flex"
				>
					<Map />
					Map and Visualize Data
					<Badge variant="new">new</Badge>
				</Button>
			{/if}
		</div>
	{/if}
</header>
