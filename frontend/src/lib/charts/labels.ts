import type { VizPayload } from '$lib/api';
import { fieldLabel } from '$lib/viz';

/** Caption lines for a single-column chart: the dataset, then the field, period and chart kind. */
export function columnCaption(data: VizPayload, col: string, kind: string): { title: string; subtitle: string } {
	const temporal = data.col_temporal[col] ?? '';
	return {
		title: data.col_dataset_titles[col] || fieldLabel(col),
		subtitle: [[fieldLabel(col), temporal].filter(Boolean).join(' · '), kind].join(' — ')
	};
}

/** Axis label for a column: the field, plus its period when there is one. */
export function columnLabel(data: VizPayload, col: string): string {
	return [fieldLabel(col), data.col_temporal[col]].filter(Boolean).join(' · ');
}
