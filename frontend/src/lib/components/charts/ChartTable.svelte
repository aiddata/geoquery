<script lang="ts" module>
	export interface TableColumn {
		key: string;
		label: string;
		/** Right-aligned in the interface face with tabular figures */
		numeric?: boolean;
		format?: (value: unknown) => string;
	}

	export interface ChartTableData {
		columns: TableColumn[];
		rows: Record<string, unknown>[];
	}
</script>

<script lang="ts">
	import * as Table from '$lib/components/ui/table';
	import { full } from '$lib/charts/plot';
	import { cn } from '$lib/utils';

	let { columns, rows }: ChartTableData = $props();

	function display(col: TableColumn, value: unknown): string {
		if (col.format) return col.format(value);
		if (typeof value === 'number') return full(value);
		if (value === null || value === undefined || value === '') return '—';
		return String(value);
	}
</script>

<!-- The chart's twin (§9.6): how keyboard and screen-reader users reach exact values -->
<div class="max-h-80 overflow-y-auto">
	<Table.Root>
		<Table.Header class="sticky top-0 bg-card">
			<Table.Row>
				{#each columns as col (col.key)}
					<Table.Head class={cn(col.numeric && 'text-right')}>{col.label}</Table.Head>
				{/each}
			</Table.Row>
		</Table.Header>
		<Table.Body>
			{#each rows as row, i (i)}
				<Table.Row>
					{#each columns as col (col.key)}
						<Table.Cell class={cn(col.numeric && 'text-right font-ui font-bold')}>
							{display(col, row[col.key])}
						</Table.Cell>
					{/each}
				</Table.Row>
			{/each}
		</Table.Body>
	</Table.Root>
</div>
