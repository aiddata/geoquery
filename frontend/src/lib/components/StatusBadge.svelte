<script lang="ts" module>
	import { Circle, CircleAlert, CircleCheck, Clock } from '@lucide/svelte';
	import type { BadgeVariant } from '$lib/components/ui/badge';

	/** The four status meanings of design-system.md §11. */
	export type StatusMeaning = 'done' | 'progress' | 'failed' | 'neutral';

	const meanings = {
		done: { variant: 'success', icon: CircleCheck },
		progress: { variant: 'warning', icon: Clock },
		failed: { variant: 'danger', icon: CircleAlert },
		neutral: { variant: 'neutral', icon: Circle }
	} satisfies Record<StatusMeaning, { variant: BadgeVariant; icon: typeof Circle }>;

	/** Request status codes from backend/analytics/services.py. */
	export function requestStatusMeaning(status: number): StatusMeaning {
		switch (status) {
			case 1:
				return 'done';
			case 0: // processing
			case 2: // preparing
			case 3: // ingesting
			case 4: // materializing
				return 'progress';
			case -2:
				return 'failed';
			default: // -1 queued, anything else
				return 'neutral';
		}
	}
</script>

<script lang="ts">
	import { Badge } from '$lib/components/ui/badge';
	import type { Snippet } from 'svelte';

	interface Props {
		meaning: StatusMeaning;
		class?: string;
		children: Snippet;
	}

	let { meaning, class: className, children }: Props = $props();

	const config = $derived(meanings[meaning]);
</script>

<Badge variant={config.variant} class={className}>
	<config.icon aria-hidden="true" />
	{@render children()}
</Badge>
