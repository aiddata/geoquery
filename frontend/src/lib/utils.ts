import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/** Convert a kwargs dict (filter_and_agg style) to a human-readable string.
 *  Range: "year: 2000–2020"   Categorical: "flow_class: ODA, OOF"
 *  Fallback for unknown shapes: JSON.stringify of the value.
 */
export function formatKwargs(kwargs: Record<string, unknown>): string {
	return Object.entries(kwargs)
		.map(([key, val]) => {
			if (val && typeof val === 'object' && !Array.isArray(val)) {
				const v = val as Record<string, unknown>;
				if (v.type === 'range') return `${key}: ${v.start}–${v.end}`;
				if (v.type === 'categorical' && Array.isArray(v.selected))
					return `${key}: ${(v.selected as string[]).join(', ')}`;
			}
			return `${key}: ${JSON.stringify(val)}`;
		})
		.join('; ');
}

// Teach tailwind-merge the design system's named sizes and shadow (layout.css @theme),
// so `text-h3` merges as a font size rather than replacing `text-foreground`.
const twMerge = extendTailwindMerge({
	extend: {
		theme: {
			text: ["h1", "h2", "h3", "h4", "field", "standfirst"],
			shadow: ["card"],
		},
	},
});

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type WithoutChild<T> = T extends { child?: any } ? Omit<T, "child"> : T;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type WithoutChildren<T> = T extends { children?: any } ? Omit<T, "children"> : T;
export type WithoutChildrenOrChild<T> = WithoutChildren<WithoutChild<T>>;
export type WithElementRef<T, U extends HTMLElement = HTMLElement> = T & { ref?: U | null };
