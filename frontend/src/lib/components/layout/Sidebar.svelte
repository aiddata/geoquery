<script lang="ts">
	import * as Sheet from '$lib/components/ui/sheet';
	import { ScrollArea } from '$lib/components/ui/scroll-area';
	import { sidebarOpen, sidebarPanel, closeSidebar } from '$lib/stores/ui';
	import CartPanel from './CartPanel.svelte';
	import HelpPanel from './HelpPanel.svelte';

	const titles = {
		cart: 'Current Request',
		help: 'Help'
	} as const;
</script>

<Sheet.Root bind:open={$sidebarOpen} onOpenChange={(open) => !open && closeSidebar()}>
	<Sheet.Content side="right" class="w-[400px] sm:w-[450px]">
		<Sheet.Header>
			<Sheet.Title>
				{$sidebarPanel && $sidebarPanel in titles ? titles[$sidebarPanel as keyof typeof titles] : ''}
			</Sheet.Title>
		</Sheet.Header>

		<ScrollArea class="h-[calc(100vh-80px)] pr-4">
			{#if $sidebarPanel === 'cart'}
				<CartPanel />
			{:else if $sidebarPanel === 'help'}
				<HelpPanel />
			{/if}
		</ScrollArea>
	</Sheet.Content>
</Sheet.Root>
