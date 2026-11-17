/**
 * Measure labels for raster extract options, carried in the description:
 * "Label {{{explanation}}}", e.g. "Minimum temperature {{{The lowest
 * temperature found anywhere in the feature, in degrees Celsius.}}}"
 * (see backend/datasets/measures.py). The checkbox value stays the extract
 * option's short name; this is display only.
 */
const MEASURE = /^\s*([\s\S]*?)\s*\{\{\{([\s\S]*?)\}\}\}\s*$/;

export function parseMeasure(shortName: string, description: string | null | undefined): { label: string; detail: string } {
	const text = description ?? '';
	const m = MEASURE.exec(text);
	if (!m) return { label: shortName, detail: text.trim() };
	return { label: m[1].trim() || shortName, detail: m[2].trim() };
}
