<script lang="ts" generics="T extends string">
	import * as Select from '$lib/components/ui/select';
	import { cn } from '$lib/utils';

	interface Props {
		value: T;
		options: { value: T; label: string }[];
		onchange: (value: T) => void;
		label: string;
		class?: string;
	}

	let { value, options, onchange, label, class: className }: Props = $props();
</script>

<Select.Root type="single" {value} onValueChange={(v) => v && onchange(v as T)}>
	<Select.Trigger size="sm" class={cn('min-w-0', className)} aria-label={label}>
		<span class="truncate">{options.find((o) => o.value === value)?.label ?? value}</span>
	</Select.Trigger>
	<Select.Content>
		{#each options as option (option.value)}
			<Select.Item value={option.value} label={option.label} />
		{/each}
	</Select.Content>
</Select.Root>
