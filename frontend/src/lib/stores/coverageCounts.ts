// How many datasets cover a set of features, as the map and Customize pages
// find out, so the request panel can show it on other steps (Review) without
// asking again. Kept for the session, by the features counted.

const counts = new Map<string, number>();

const keyOf = (featureIds: number[]) => featureIds.join(',');

export function rememberCoverage(featureIds: number[], count: number): void {
	if (featureIds.length > 0) counts.set(keyOf(featureIds), count);
}

export function knownCoverage(featureIds: number[]): number | undefined {
	return counts.get(keyOf(featureIds));
}
