import { describe, expect, test } from 'bun:test';
import type { VizPayload } from '$lib/api';
import {
	columnValues,
	getTemporalSeries,
	numericValue,
	pearsonCorrelation,
	pearsonMatrix
} from '$lib/viz';

function payload(features: Record<string, Record<string, string | number | null>>): VizPayload {
	const columns = [...new Set(Object.values(features).flatMap((f) => Object.keys(f)))];
	return {
		fc_names: ['fc'],
		columns,
		col_groups: {},
		col_descriptions: {},
		col_dataset_titles: Object.fromEntries(columns.map((c) => [c, 'Pop'])),
		col_temporal: Object.fromEntries(columns.map((c) => [c, c.slice(-4)])),
		features: Object.fromEntries(
			Object.entries(features).map(([id, f]) => [id, { name: `f${id}`, fc: 'fc', ...f }])
		),
		bbox: null
	};
}

describe('numericValue', () => {
	test('treats null, undefined and empty strings as missing rather than zero', () => {
		expect(numericValue(null)).toBeNull();
		expect(numericValue(undefined)).toBeNull();
		expect(numericValue('')).toBeNull();
		expect(numericValue('abc')).toBeNull();
		expect(numericValue(Infinity)).toBeNull();
	});

	test('keeps real zeros and numeric strings', () => {
		expect(numericValue(0)).toBe(0);
		expect(numericValue('2.5')).toBe(2.5);
	});
});

describe('columnValues', () => {
	test('skips missing values', () => {
		const data = payload({ 1: { a: 1 }, 2: { a: null }, 3: { a: 0 } });
		expect(columnValues(data, 'a')).toEqual([1, 0]);
	});
});

describe('getTemporalSeries', () => {
	test('averages only the features that have a value', () => {
		const data = payload({ 1: { pop_2000: 10 }, 2: { pop_2000: null }, 3: { pop_2000: 20 } });
		const [entry] = getTemporalSeries(data, 'Pop');
		expect(entry.mean).toBe(15);
		expect(entry.min).toBe(10);
		expect(entry.values).toEqual([10, 20]);
	});

	test('reports a period with no values as null, not zero', () => {
		const data = payload({ 1: { pop_2000: null, pop_2001: 5 } });
		const series = getTemporalSeries(data, 'Pop');
		expect(series[0].mean).toBeNull();
		expect(series[0].max).toBeNull();
		expect(series[1].mean).toBe(5);
	});
});

describe('pearsonCorrelation', () => {
	test('is undefined (NaN) without at least two pairs or without variance', () => {
		expect(pearsonCorrelation([1], [2])).toBeNaN();
		expect(pearsonCorrelation([1, 1, 1], [1, 2, 3])).toBeNaN();
	});
});

describe('pearsonMatrix', () => {
	test('pairs values by feature when columns are missing values on different features', () => {
		// a and b are perfectly correlated on the features where both exist (1, 3, 4).
		// Feature 2 has only a, feature 5 only b; a per-column filter would misalign them.
		const data = payload({
			1: { a: 1, b: 10 },
			2: { a: 100, b: null },
			3: { a: 2, b: 20 },
			4: { a: 3, b: 30 },
			5: { a: null, b: -50 }
		});
		const m = pearsonMatrix(data, ['a', 'b']);
		expect(m[0][1]).toBeCloseTo(1, 10);
		expect(m[1][0]).toBeCloseTo(1, 10);
		expect(m[0][0]).toBeCloseTo(1, 10);
	});
});
