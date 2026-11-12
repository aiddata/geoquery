import type { DatasetDetail } from '#lib/api.js';

/** Kilometres per degree of longitude at the equator. */
const KM_PER_DEGREE = 111.32;

/** "0.00833° (~930 m)": the stored cell size, and roughly what it is on the ground. */
export function formatResolution(degrees: number | null): string | null {
	if (degrees == null || !(degrees > 0)) return null;
	const km = degrees * KM_PER_DEGREE;
	const ground =
		km >= 10
			? `${Math.round(km)} km`
			: km >= 1
				? `${km.toFixed(1)} km`
				: `${Math.round((km * 1000) / 10) * 10} m`;
	return `${Number(degrees.toPrecision(3))}° (~${ground} at the equator)`;
}

function formatMonth(iso: string): string {
	return new Date(iso).toLocaleDateString('en-US', {
		year: 'numeric',
		month: 'short',
		timeZone: 'UTC'
	});
}

/** "2000–2020 (21 time steps)", "Jan 2015 – Dec 2020", or "Time-invariant". */
export function formatTimeCoverage(
	dataset: Pick<
		DatasetDetail,
		'temporal_name' | 'temporal_type' | 'temporal_start' | 'temporal_end' | 'resources'
	>
): string {
	const { temporal_start: start, temporal_end: end } = dataset;
	if (!start || dataset.temporal_name?.toLowerCase().includes('invariant')) {
		return 'Time-invariant';
	}
	const monthly = dataset.temporal_type?.includes('month');
	const label = (iso: string) =>
		monthly ? formatMonth(iso) : String(new Date(iso).getUTCFullYear());
	const from = label(start);
	const to = end ? label(end) : null;
	const range = !to || to === from ? from : monthly ? `${from} – ${to}` : `${from}–${to}`;
	const steps = dataset.resources?.length ?? 0;
	return steps > 1 ? `${range} (${steps} time steps)` : range;
}

export function formatSpatialCoverage(
	isGlobal: boolean,
	bbox: [number, number, number, number] | null | undefined
): string {
	// An extent spanning the world is global even when the flag was not set.
	const spansWorld = !!bbox && bbox[2] - bbox[0] >= 359 && bbox[3] - bbox[1] >= 170;
	if (isGlobal || spansWorld) return 'Global';
	if (!bbox) return 'Regional';
	const [xmin, ymin, xmax, ymax] = bbox.map((v) => v.toFixed(1));
	return `Regional (longitude ${xmin} to ${xmax}, latitude ${ymin} to ${ymax})`;
}

export function formatAddedUpdated(added: string | null, updated: string | null): string | null {
	const parts = [added, updated].filter((d): d is string => !!d).map(formatMonth);
	if (parts.length === 0) return null;
	return parts.length === 2 && parts[0] !== parts[1] ? `${parts[0]} / ${parts[1]}` : parts[0];
}

/** Text split into plain runs and URLs, so URLs can be rendered as links. */
export function linkParts(text: string): { text: string; href?: string }[] {
	const parts: { text: string; href?: string }[] = [];
	let last = 0;
	for (const m of text.matchAll(/https?:\/\/[^\s<>"]+/g)) {
		// A sentence's closing punctuation is not part of the URL.
		const url = m[0].replace(/[.,;:!?)\]]+$/, '');
		const at = m.index ?? 0;
		if (at > last) parts.push({ text: text.slice(last, at) });
		parts.push({ text: url, href: url });
		last = at + url.length;
	}
	if (last < text.length) parts.push({ text: text.slice(last) });
	return parts;
}
