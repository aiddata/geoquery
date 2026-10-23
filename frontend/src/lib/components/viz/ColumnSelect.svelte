<script lang="ts">
	import type { VizPayload } from '$lib/api';
	import { columnLabel } from '$lib/charts/labels';
	import * as Select from '$lib/components/ui/select';
	import { cn } from '$lib/utils';

	interface Props {
		data: VizPayload;
		value: string;
		onchange: (col: string) => void;
		label: string;
		class?: string;
	}

	let { data, value, onchange, label, class: className }: Props = $props();
</script>

<!-- A column picker grouped by resource, the shadcn equivalent of <select> with <optgroup>s -->
<Select.Root type="single" {value} onValueChange={(v) => v && onchange(v)}>
	<Select.Trigger size="sm" class={cn('min-w-0', className)} aria-label={label}>
		<span class="truncate">{value ? columnLabel(data, value) : 'Choose a column'}</span>
	</Select.Trigger>
	<Select.Content>
		{#each Object.entries(data.col_groups) as [group, cols] (group)}
			<Select.Group>
				<Select.GroupHeading>{group}</Select.GroupHeading>
				{#each cols as col (col)}
					<Select.Item value={col} label={columnLabel(data, col)} />
				{/each}
			</Select.Group>
		{/each}
	</Select.Content>
</Select.Root>
