<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import UserMenu from '#lib/components/layout/UserMenu.svelte';
	import { features } from '#lib/stores/features.js';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.js';
	import { ChevronUp, Map, Menu as MenuIcon } from '@lucide/svelte';
	import aiddataLogo from '#lib/assets/aiddata_logo.svg';
	import aiddataLogoWhite from '#lib/assets/aiddata_logo_white.png';
	import geoqueryText from '#lib/assets/geoquery_text.svg';

	// Shown as text links on wide screens and in the menu on narrower ones.
	type NavLink = { label: string; href?: string; external?: boolean; onclick?: () => void };
	const navLinks: NavLink[] = [
		{ label: 'About', href: 'https://www.aiddata.org/geoquery', external: true },
		{ label: 'Documentation', href: 'https://docs.geoquery.org/', external: true },
		// The news page: markdown posts in docs/updates/posts/, published with the docs.
		{ label: 'Updates', href: 'https://docs.geoquery.org/updates/', external: true }
		// Past Requests is in the Account menu, signed in or not.
	];

	// The map and visualize views (beta), first in the navigation for those
	// who have them. The request steps need no bar of their own: the request
	// panel on each step page shows where you are (GEO-149).
	const showViz = $derived($features.has('visualize'));

	// Published as --header-height, so the step pages can fill the rest of the
	// screen whatever the header's height
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
     17px), so the header keeps its proportions if the base text size changes.
     The gold rule divides it from every page below, whatever that page's top
     is: the raised open step, the band of a collapsed one, or dark mode. -->
<header
	bind:offsetHeight={headerHeight}
	class="sticky top-0 z-50 w-full border-b-[3px] border-gold bg-card shadow-card [--lh:calc(var(--text-base--line-height)*1em)]"
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
				{#if showViz}
					<Button variant="ghost" href="/viz/explore">
						<Map />
						Map and Visualize Data
						<Badge variant="new">new</Badge>
					</Button>
					<span class="h-5 w-px bg-border" aria-hidden="true"></span>
				{/if}
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
				<DropdownMenu.Content align="end" class="w-64">
					{#if showViz}
						<DropdownMenu.Item>
							{#snippet child({ props })}
								<a {...props} href="/viz/explore">
									<Map />
									Map and Visualize Data
									<Badge variant="new">new</Badge>
								</a>
							{/snippet}
						</DropdownMenu.Item>
						<DropdownMenu.Separator />
					{/if}
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
</header>
