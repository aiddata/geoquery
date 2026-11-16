<script lang="ts">
	import type { DatasetDetail } from '#lib/api.js';
	import type { CartItem } from '#lib/stores/cart.js';
	import { cleanVersionName, entryColumns, narrowedFilters } from '#lib/utils/outputColumns.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { Pencil, Trash2 } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';

	// A feature dataset's versions in the request, one card each. Clicking a
	// card loads that version into the options below to edit, so Update
	// Request replaces it (as "Edit options" on Review does).
	interface Props {
		dataset: DatasetDetail;
		/** This dataset's entries, with their position in the request */
		entries: { item: CartItem; index: number }[];
		/** Request positions whose name is empty or a duplicate */
		invalid: Set<number>;
		onRename: (index: number, name: string) => void;
		/** Remove this version from the request */
		onRemove: (index: number) => void;
		/** kwargs key of the version being edited, if any */
		editingKey: string | null;
		/** kwargs key of the options shown below */
		currentKey: string;
		onEdit: (item: CartItem) => void;
	}

	let { dataset, entries, invalid, onRename, onRemove, editingKey, currentKey, onEdit }: Props = $props();

	const keyOf = (item: CartItem) => JSON.stringify(item.kwargs ?? null);

	function details(item: CartItem) {
		const outcome = item.kwargs?.outcome;
		const measure = typeof outcome === 'string' ? (dataset.outcomes?.[outcome] ?? outcome) : null;
		const splits = Object.entries(dataset.filters ?? {})
			.filter(([, f]) => f.aggregate === false)
			.map(([key, f]) => {
				const sel = item.filterSelections?.[key];
				return `${f.display ?? key} (${sel?.type === 'categorical' ? sel.selected.length : 'all'})`;
			});
		const cols = entryColumns(item);
		return {
			line: [measure, `${cols.toLocaleString()} column${cols === 1 ? '' : 's'}`, splits.length ? `split by ${splits.join(', ')}` : null]
				.filter(Boolean)
				.join(' · '),
			filters: narrowedFilters(dataset.filters, item.filterSelections)
		};
	}
</script>

<section aria-labelledby="versions-heading" class="mx-4 mt-4">
	<h3 id="versions-heading" class="mb-2 text-sm font-bold">
		In your request <span class="font-normal text-muted-foreground">({entries.length} version{entries.length === 1 ? '' : 's'})</span>
	</h3>
	<div class="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
		{#each entries as { item, index } (keyOf(item))}
			{@const d = details(item)}
			{@const key = keyOf(item)}
			<div
				class="flex flex-col rounded-md border bg-card transition-colors hover:border-primary
					{editingKey === key ? 'border-primary ring-1 ring-primary' : ''}"
			>
				<!-- The name prefixes this version's output columns -->
				<div class="flex items-center gap-2 px-3 pt-3">
					<label for="version-name-{index}" class="sr-only">Version name</label>
					<Input
						id="version-name-{index}"
						value={item.customName}
						oninput={(e) => {
							const el = e.target as HTMLInputElement;
							el.value = cleanVersionName(el.value);
							onRename(index, el.value);
						}}
						aria-invalid={invalid.has(index) || undefined}
						class="h-8 font-ui text-sm font-bold"
					/>
					{#if editingKey === key}
						<span class="shrink-0 rounded-full bg-primary px-2 py-0.5 text-xs font-bold text-primary-foreground">Editing</span>
					{:else if currentKey === key}
						<span class="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">Shown below</span>
					{/if}
					<Button
						variant="ghost"
						size="icon-sm"
						class="shrink-0 text-muted-foreground hover:text-destructive"
						aria-label="Remove {item.customName || 'this version'} from your request"
						onclick={() => onRemove(index)}
					>
						<Trash2 />
					</Button>
				</div>
				{#if invalid.has(index)}
					<p class="px-3 pt-1 text-xs text-destructive">
						{item.customName ? 'Another version already uses this name.' : 'Give this version a name.'}
					</p>
				{/if}
				<button
					type="button"
					onclick={() => onEdit(item)}
					aria-pressed={editingKey === key}
					class="group flex-1 rounded-b-md px-3 pb-3 pt-2 text-left focus-visible:outline-2 focus-visible:outline-ring"
				>
					<span class="block text-xs text-muted-foreground">{d.line}</span>
					<span class="mt-0.5 block truncate text-xs text-muted-foreground">
						{d.filters.length ? `Filtered by ${d.filters.join(', ')}` : 'No filters narrowed'}
					</span>
					<span class="mt-1.5 flex items-center gap-1 text-xs font-bold text-primary group-hover:underline">
						<Pencil class="size-3" aria-hidden="true" />
						{editingKey === key ? 'Editing below' : 'Edit this version'}
					</span>
				</button>
			</div>
		{/each}
	</div>
</section>
