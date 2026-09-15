export function quantileBreaks(values: number[], n: number): number[] {
	const sorted = [...values].sort((a, b) => a - b);
	if (!sorted.length) return [];
	if (sorted[0] === sorted[sorted.length - 1]) return Array.from({ length: n + 1 }, () => sorted[0]);
	const breaks = [sorted[0]];
	for (let i = 1; i <= n; i++) breaks.push(sorted[Math.round((i / n) * (sorted.length - 1))]);
	return breaks;
}

export function equalBreaks(values: number[], n: number): number[] {
	if (!values.length) return [];
	const min = Math.min(...values);
	const max = Math.max(...values);
	const step = (max - min) / n;
	return Array.from({ length: n + 1 }, (_, i) => min + i * step);
}

export function temporalTrack(column: string, temporal: string): string {
	const escaped = temporal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	return column.replace(new RegExp(`[_.]?${escaped}(?=\\.|$)`), '');
}

export function hasSingleTemporalTrack(columns: Array<{ name: string; temporal?: string | null }>): boolean {
	const temporal = columns.filter((column) => column.temporal);
	return temporal.length > 1 && new Set(temporal.map((column) => temporalTrack(column.name, column.temporal!))).size === 1;
}
