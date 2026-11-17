import { describe, expect, test } from 'bun:test';
import type { CartItem } from '#lib/stores/cart.js';
import { mergeFeatureVersions, versionCovers } from './featureMerge';

const split = (selected: string[]) => ({ type: 'categorical', aggregate: false, selected });
const filter = (selected: string[]) => ({ type: 'categorical', aggregate: true, selected });

function version(name: string, kwargs: Record<string, unknown>): CartItem {
	const filterSelections: CartItem['filterSelections'] = {};
	for (const [k, v] of Object.entries(kwargs)) {
		if (k === 'outcome') continue;
		const { aggregate: _a, ...sel } = v as { aggregate: boolean; type: 'categorical'; selected: string[] };
		filterSelections[k] = sel;
	}
	return {
		customName: name,
		datasetName: 'acled',
		datasetTitle: 'ACLED',
		datasetType: 'feature',
		processingClass: 'filter_and_agg',
		filterSelections,
		kwargs
	};
}

describe('mergeFeatureVersions', () => {
	test('unions the years of versions that differ only in years', () => {
		const a = version('acled', { outcome: 'count', year: split(['2012', '2010']), type: filter(['Battles']) });
		const b = version('acled_2', { outcome: 'count', year: split(['2011', '2012']), type: filter(['Battles']) });
		const merged = mergeFeatureVersions(a, b)!;
		expect(merged.customName).toBe('acled');
		expect((merged.kwargs!.year as { selected: string[] }).selected).toEqual(['2010', '2011', '2012']);
		expect((merged.filterSelections!.year as { selected: string[] }).selected).toEqual(['2010', '2011', '2012']);
		expect(merged.kwargs!.type).toEqual(filter(['Battles']));
	});

	test('handles years stored as numbers', () => {
		const a = version('a', { year: { type: 'categorical', aggregate: false, selected: [2001, 1999] } });
		const b = version('b', { year: { type: 'categorical', aggregate: false, selected: [2000] } });
		expect((mergeFeatureVersions(a, b)!.kwargs!.year as { selected: number[] }).selected).toEqual([1999, 2000, 2001]);
		expect(versionCovers(a, { year: { type: 'categorical', aggregate: false, selected: [1999] } })).toBe(true);
	});

	test('keeps first-seen order for non-numeric splits', () => {
		const a = version('a', { kind: split(['Riots', 'Battles']) });
		const b = version('b', { kind: split(['Protests', 'Battles']) });
		expect((mergeFeatureVersions(a, b)!.kwargs!.kind as { selected: string[] }).selected).toEqual([
			'Riots',
			'Battles',
			'Protests'
		]);
	});

	test('returns the existing version unchanged when identical', () => {
		const a = version('a', { year: split(['2010']) });
		expect(mergeFeatureVersions(a, version('b', { year: split(['2010']) }))).toBe(a);
	});

	test('does not merge when a filter differs', () => {
		const a = version('a', { year: split(['2010']), type: filter(['Battles']) });
		const b = version('b', { year: split(['2011']), type: filter(['Riots']) });
		expect(mergeFeatureVersions(a, b)).toBeNull();
	});

	test('does not merge when the measure differs', () => {
		const a = version('a', { outcome: 'count', year: split(['2010']) });
		const b = version('b', { outcome: 'fatalities', year: split(['2011']) });
		expect(mergeFeatureVersions(a, b)).toBeNull();
	});

	test('does not merge when two split fields differ', () => {
		const a = version('a', { year: split(['2010']), kind: split(['Riots']) });
		const b = version('b', { year: split(['2011']), kind: split(['Battles']) });
		expect(mergeFeatureVersions(a, b)).toBeNull();
	});

	test('does not merge across datasets or with rasters', () => {
		const a = version('a', { year: split(['2010']) });
		expect(mergeFeatureVersions(a, { ...version('b', { year: split(['2011']) }), datasetName: 'other' })).toBeNull();
		expect(mergeFeatureVersions(a, { ...a, kwargs: undefined })).toBeNull();
	});
});

describe('versionCovers', () => {
	const a = version('a', { outcome: 'count', year: split(['2010', '2011', '2012']) });
	test('covers identical options and a subset of years', () => {
		expect(versionCovers(a, a.kwargs!)).toBe(true);
		expect(versionCovers(a, { outcome: 'count', year: split(['2011']) })).toBe(true);
	});
	test('does not cover new years or a different measure', () => {
		expect(versionCovers(a, { outcome: 'count', year: split(['2013']) })).toBe(false);
		expect(versionCovers(a, { outcome: 'fatalities', year: split(['2011']) })).toBe(false);
	});
});
