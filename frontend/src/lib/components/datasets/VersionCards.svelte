<script lang="ts">
	import type { DatasetDetail } from '#lib/api.js';
	import type { CartItem } from '#lib/stores/cart.js';
	import { cleanVersionName, entryColumns, narrowedFilters } from '#lib/utils/outputColumns.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { CircleAlert, CircleCheck, Pencil, Plus, Trash2 } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';

	// A feature dataset's selections, one card each (GEO-153). The one being
	// edited is highlighted, and the options below save to it as they change.
	// A complete selection is in the request (check); an incomplete one exists
	// only here, as the draft card (warning), until it's complete. Clicking a
	// card edits it; New selection keeps the current one and starts another.
	interface Props {
		dataset: DatasetDetail;
		/** This dataset's selections in the request, with their position in it */
		entries: { item: CartItem; index: number }[];
		/** Request positions whose name is empty or a duplicate */
		invalid: Set<number>;
		onRename: (index: number, name: string) => void;
		/** Remove this selection from the request */
		onRemove: (index: number) => void;
		/** kwargs key of the selection being edited, while it's in the request */
		editingKey: string | null;
		onEdit: (item: CartItem) => void;
		/** The selection being edited when it isn't in the request: its name, and why not (a sentence) */
		draft: { name: string; problem: string } | null;
		onNew: () => void;
		/** The selection being edited is saved, so starting another loses nothing */
		canNew: boolean;
	}

	let { dataset, entries, invalid, onRename, onRemove, editingKey, onEdit, draft, onNew, canNew }: Props = $props();

	const keyOf = (item: CartItem) => JSON.stringify(item.kwargs ?? null);
	const count = $derived(entries.length + (draft ? 1 : 0));

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
	<div class="mb-2 flex items-center justify-between gap-2">
		<h3 id="versions-heading" class="text-sm font-bold">
			Selections <span class="font-normal text-muted-foreground">({count})</span>
		</h3>
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<Button
						{...props}
						variant="outline"
						size="sm"
						onclick={() => canNew && onNew()}
						aria-disabled={!canNew || undefined}
						class={canNew ? '' : 'cursor-not-allowed opacity-50'}
					>
						<Plus />
						New selection
					</Button>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content>
				{canNew
					? 'Keep this selection in your request, and start another with different options'
					: 'Finish this selection first: it needs its options complete, and different from the others'}
			</Tooltip.Content>
		</Tooltip.Root>
	</div>
	<div class="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
		{#each entries as { item, index } (keyOf(item))}
			{@const d = details(item)}
			{@const editing = editingKey === keyOf(item)}
			<div
				class="flex flex-col rounded-md border bg-card transition-colors hover:border-primary
					{editing ? 'border-primary ring-1 ring-primary' : ''}"
			>
				<!-- The name prefixes this selection's output columns -->
				<div class="flex items-center gap-2 px-3 pt-3">
					<CircleCheck class="size-4 shrink-0 text-success-text" aria-hidden="true" />
					<label for="version-name-{index}" class="sr-only">Selection name (in your request)</label>
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
					{#if editing}
						<span class="shrink-0 rounded-full bg-primary px-2 py-0.5 text-xs font-bold text-primary-foreground">Editing</span>
					{/if}
					<Button
						variant="ghost"
						size="icon-sm"
						class="shrink-0 text-muted-foreground hover:text-destructive"
						aria-label="Remove {item.customName || 'this selection'} from your request"
						onclick={() => onRemove(index)}
					>
						<Trash2 />
					</Button>
				</div>
				{#if invalid.has(index)}
					<p class="px-3 pt-1 text-xs text-destructive">
						{item.customName ? 'Another selection already uses this name.' : 'Give this selection a name.'}
					</p>
				{/if}
				<button
					type="button"
					onclick={() => onEdit(item)}
					aria-pressed={editing}
					class="group flex-1 rounded-b-md px-3 pb-3 pt-2 text-left focus-visible:outline-2 focus-visible:outline-ring"
				>
					<span class="block text-xs text-muted-foreground">{d.line}</span>
					<span class="mt-0.5 block truncate text-xs text-muted-foreground">
						{d.filters.length ? `Filtered by ${d.filters.join(', ')}` : 'No filters narrowed'}
					</span>
					<span class="mt-1.5 flex items-center gap-1 text-xs font-bold text-primary group-hover:underline">
						<Pencil class="size-3" aria-hidden="true" />
						{editing ? 'Editing below' : 'Edit this selection'}
					</span>
				</button>
			</div>
		{/each}
		{#if draft}
			<!-- The selection being edited, not in the request yet -->
			<div class="flex flex-col rounded-md border border-primary bg-card ring-1 ring-primary">
				<div class="flex items-center gap-2 px-3 pt-3">
					<CircleAlert class="size-4 shrink-0 text-warning-text" aria-hidden="true" />
					<span class="min-w-0 flex-1 truncate font-ui text-sm font-bold">{draft.name}</span>
					<span class="shrink-0 rounded-full bg-primary px-2 py-0.5 text-xs font-bold text-primary-foreground">Editing</span>
				</div>
				<p class="px-3 pb-3 pt-2 text-xs text-muted-foreground">{draft.problem}</p>
			</div>
		{/if}
	</div>
</section>
