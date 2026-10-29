/** [west, south, east, north] in degrees. */
export type Bbox = [number, number, number, number];

/** Smallest bbox covering every given bbox; null when none is given. */
export function unionBbox(bboxes: (Bbox | null | undefined)[]): Bbox | null {
	const valid = bboxes.filter(Boolean) as Bbox[];
	if (valid.length === 0) return null;
	return [
		Math.min(...valid.map((b) => b[0])),
		Math.min(...valid.map((b) => b[1])),
		Math.max(...valid.map((b) => b[2])),
		Math.max(...valid.map((b) => b[3]))
	];
}
