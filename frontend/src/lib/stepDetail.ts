/**
 * Narrow screens (below md) show a request step's panel or its detail view
 * (the page's .step-main: the map, a dataset, the review), not both; wider
 * screens show both side by side. The panel is where the step's flow is, and
 * each step has its own way into the detail: Show map, picking a dataset,
 * Review your request. Each detail view has a back button.
 *
 * The open detail is a shallow history entry (page.state.detail), so the
 * phone's back gesture closes it rather than leaving the step, and every page
 * opens on its panel. layout.css ("Narrow step pages") does the showing and
 * hiding, from data-detail on the layout's wrapper.
 */
import { pushState } from '$app/navigation';
import { page } from '$app/state';

/** Matches Tailwind's md breakpoint, below which the panel is full width. */
const NARROW = '(width < 48rem)';

export function isNarrow(): boolean {
	return typeof window !== 'undefined' && window.matchMedia(NARROW).matches;
}

/** Show the step's detail view. Wide screens already show it: no-op there. */
export function openDetail(): void {
	if (!isNarrow() || page.state.detail) return;
	pushState('', { detail: true });
}

/** Back to the panel, as the back gesture would. */
export function closeDetail(): void {
	if (page.state.detail) history.back();
}
