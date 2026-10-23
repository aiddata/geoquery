<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
	import { resolvedTheme, themePreference, type ThemePreference } from '$lib/stores/theme';
	import { Monitor, Moon, Sun } from '@lucide/svelte';

	const options: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
		{ value: 'light', label: 'Light', icon: Sun },
		{ value: 'dark', label: 'Dark', icon: Moon },
		{ value: 'system', label: 'System', icon: Monitor }
	];
</script>

<DropdownMenu.Root>
	<DropdownMenu.Trigger>
		{#snippet child({ props })}
			<Button {...props} variant="ghost" size="icon" aria-label="Theme">
				{#if $resolvedTheme === 'dark'}
					<Moon />
				{:else}
					<Sun />
				{/if}
			</Button>
		{/snippet}
	</DropdownMenu.Trigger>
	<DropdownMenu.Content align="end" class="w-40">
		<DropdownMenu.Label>Theme</DropdownMenu.Label>
		<DropdownMenu.RadioGroup bind:value={$themePreference}>
			{#each options as option (option.value)}
				<DropdownMenu.RadioItem value={option.value}>
					<option.icon />
					{option.label}
				</DropdownMenu.RadioItem>
			{/each}
		</DropdownMenu.RadioGroup>
	</DropdownMenu.Content>
</DropdownMenu.Root>
