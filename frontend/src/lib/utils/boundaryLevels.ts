import type { BoundaryResult } from '#lib/api.js';

export type LevelKey = number | 'Unspecified';

/** Boundary sets grouped by administrative level, in level order with unspecified levels last. */
export function groupByLevel(boundaries: BoundaryResult[]): Map<LevelKey, BoundaryResult[]> {
	const groups = new Map<LevelKey, BoundaryResult[]>();
	for (const b of boundaries) {
		const level: LevelKey = b.group_level ?? 'Unspecified';
		if (!groups.has(level)) groups.set(level, []);
		groups.get(level)!.push(b);
	}
	const order = (k: LevelKey) => (typeof k === 'number' ? k : Infinity);
	return new Map([...groups.entries()].sort((a, b) => order(a[0]) - order(b[0])));
}

const LEVEL_NAMES = ['Country', 'Region/State', 'District/County', 'Municipality/City', 'Village/Ward'];

export const levelLabel = (k: LevelKey) =>
	typeof k !== 'number' ? 'Other' : LEVEL_NAMES[k] ? `ADM${k} (${LEVEL_NAMES[k]})` : `ADM${k}`;
