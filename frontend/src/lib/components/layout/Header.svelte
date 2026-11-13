<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import UserMenu from '#lib/components/layout/UserMenu.svelte';
	import ThemeMenu from '#lib/components/layout/ThemeMenu.svelte';
	import { openSidebar, currentStep, type Step } from '#lib/stores/ui.js';
	import { features } from '#lib/stores/features.js';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.js';
	import { ChevronUp, Map, Menu as MenuIcon } from '@lucide/svelte';
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
		{ label: 'Help', onclick: () => openSidebar('help') },
		{ label: 'Past Requests', href: '/requests' }
	];

	const steps: { id: Step; label: string }[] = [
		{ id: 'map', label: '1. Select Boundary' },
		{ id: 'search', label: '2. Customize Datasets' },
		{ id: 'review', label: '3. Review Request' }
	];
</script>

<!-- Small arrow at the top right of a link that opens another site. -->
{#snippet externalMark()}
	<ChevronUp class="-ml-1.5 -mt-0.5 size-2.5 rotate-[40deg] self-start text-muted-foreground" stroke-width={3} aria-hidden="true" />
	<span class="sr-only">(opens in a new tab)</span>
{/snippet}

<header class="sticky top-0 z-50 w-full bg-card shadow-card">
	<!-- Main Header -->
	<div class="flex min-h-20 items-center justify-between px-4">
		<!-- Logo -->
		<div class="flex shrink-0 items-center gap-3">
			<!-- AidData's own white-lettered logo for dark mode; the triangles keep their colours. -->
			<a
				href="https://www.aiddata.org/"
				target="_blank"
				rel="noopener noreferrer"
				aria-label="AidData (opens in a new tab)"
			>
				<img src={aiddataLogo} alt="" class="h-[2.3rem] w-auto sm:h-[2.875rem] dark:hidden" />
				<img src={aiddataLogoWhite} alt="" class="hidden h-[2.3rem] w-auto sm:h-[2.875rem] dark:block" />
			</a>
			<span class="hidden h-10 w-px bg-border md:block" aria-hidden="true"></span>
			<a href="/" class="hidden md:block" aria-label="GeoQuery home">
				<img src={geoqueryText} alt="" class="h-10 w-auto brightness-0 dark:invert" />
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

	<!-- Step Indicator (only on workflow pages) -->
	{#if showSteps}
		<div class="flex min-h-12 items-center justify-between bg-band px-4">
			<div class="flex items-center gap-1 sm:gap-2">
				{#each steps as step, i}
					{#if i > 0}
						<span class="text-muted-foreground">/</span>
					{/if}
					<span
						class="flex items-center rounded-md px-2 py-1.5 text-sm font-bold sm:px-3
							{$currentStep === step.id
							? 'bg-primary text-primary-foreground'
							: 'text-muted-foreground'}"
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
