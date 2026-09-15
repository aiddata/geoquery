import { describe, expect, test } from 'bun:test';
import { equalBreaks, hasSingleTemporalTrack, quantileBreaks } from './map';

describe('MCP map helpers', () => {
	test('computes classifications', () => {
		expect(equalBreaks([0, 10], 2)).toEqual([0, 5, 10]);
		expect(quantileBreaks([1, 2, 3, 4, 5], 2)).toEqual([1, 3, 5]);
	});

	test('shows a year slider only for one measure track', () => {
		expect(hasSingleTemporalTrack([
			{ name: 'population_2000.sum', temporal: '2000' },
			{ name: 'population_2005.sum', temporal: '2005' }
		])).toBeTrue();
		expect(hasSingleTemporalTrack([
			{ name: 'population_2000.sum', temporal: '2000' },
			{ name: 'lights_2005.mean', temporal: '2005' }
		])).toBeFalse();
	});
});
