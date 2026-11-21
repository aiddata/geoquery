/**
 * Time period labels as people read them (GEO-161). Raster periods are
 * labelled as the data names them: "2010" for a year, "199501" for a month,
 * "19950115" for a day. Stored labels stay as they are (requests, recipes and
 * the request's documentation use them); these are for display.
 */

const MONTHS = [
	'January', 'February', 'March', 'April', 'May', 'June',
	'July', 'August', 'September', 'October', 'November', 'December'
];

const MONTH = /^(\d{4})(0[1-9]|1[0-2])$/;
const DAY = /^(\d{4})(0[1-9]|1[0-2])(\d{2})$/;

/** "199501" → "1995 January", "19950115" → "1995-01-15"; anything else unchanged. */
export function formatPeriod(label: string): string {
	const m = MONTH.exec(label);
	if (m) return `${m[1]} ${MONTHS[Number(m[2]) - 1]}`;
	const d = DAY.exec(label);
	if (d) return `${d[1]}-${d[2]}-${d[3]}`;
	return label;
}

/** A month label's position on a single count (year × 12 + month), or null. */
function monthIndex(label: string): number | null {
	const m = MONTH.exec(label);
	return m ? Number(m[1]) * 12 + Number(m[2]) - 1 : null;
}

/** "1992–2013", "1995 January – 2020 December": the span of some periods, in order. */
export function periodRange(labels: string[]): string | null {
	if (labels.length === 0) return null;
	const first = formatPeriod(labels[0]);
	const last = formatPeriod(labels.at(-1)!);
	if (labels.length === 1 || first === last) return first;
	// An en dash between years; spaced when the ends have spaces themselves
	return /\s/.test(first) || /\s/.test(last) ? `${first} – ${last}` : `${first}–${last}`;
}

/**
 * Periods for chips: a run of consecutive years or months becomes one range,
 * otherwise each period is formatted on its own.
 */
export function compactPeriods(labels: string[]): string[] {
	if (labels.length > 2) {
		if (labels.every((v) => /^\d{4}$/.test(v))) {
			const years = labels.map(Number).sort((a, b) => a - b);
			if (years.every((y, i) => i === 0 || y === years[i - 1] + 1)) return [`${years[0]}–${years.at(-1)}`];
		}
		const months = labels.map(monthIndex);
		if (months.every((v) => v !== null)) {
			const order = labels.map((l, i) => [l, months[i]!] as const).sort((a, b) => a[1] - b[1]);
			if (order.every(([, v], i) => i === 0 || v === order[i - 1][1] + 1)) {
				return [periodRange(order.map(([l]) => l))!];
			}
		}
	}
	return labels.map(formatPeriod);
}

/** What to call a number of these periods: years, months, or time periods. */
export function periodUnit(labels: string[]): [one: string, many: string] {
	if (labels.length > 0 && labels.every((l) => /^\d{4}$/.test(l))) return ['year', 'years'];
	if (labels.length > 0 && labels.every((l) => MONTH.test(l))) return ['month', 'months'];
	return ['time period', 'time periods'];
}
