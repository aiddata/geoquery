import { describe, expect, test } from 'bun:test';
import {
	formatAddedUpdated,
	formatResolution,
	formatSpatialCoverage,
	formatTimeCoverage,
	linkParts
} from './datasetMetadata';

describe('formatResolution', () => {
	test('shows degrees and the approximate ground distance', () => {
		expect(formatResolution(0.008333333333333)).toBe('0.00833° (~930 m at the equator)');
		expect(formatResolution(0.01)).toBe('0.01° (~1.1 km at the equator)');
		expect(formatResolution(0.5)).toBe('0.5° (~56 km at the equator)');
	});
	test('is null when unknown', () => {
		expect(formatResolution(null)).toBeNull();
		expect(formatResolution(0)).toBeNull();
	});
});

describe('formatTimeCoverage', () => {
	const base = { temporal_name: 'Datetime', resources: [] as never[] };
	test('yearly range with time steps', () => {
		expect(
			formatTimeCoverage({
				...base,
				temporal_type: 'year',
				temporal_start: '2000-01-01T00:00:00Z',
				temporal_end: '2020-01-01T00:00:00Z',
				resources: new Array(21) as never[]
			})
		).toBe('2000–2020 (21 time steps)');
	});
	test('monthly range', () => {
		expect(
			formatTimeCoverage({
				...base,
				temporal_type: 'year month',
				temporal_start: '2015-01-01T00:00:00Z',
				temporal_end: '2020-12-01T00:00:00Z'
			})
		).toBe('Jan 2015 – Dec 2020');
	});
	test('a single year, and time-invariant data', () => {
		expect(
			formatTimeCoverage({
				...base,
				temporal_type: 'year',
				temporal_start: '2015-01-01T00:00:00Z',
				temporal_end: '2015-01-01T00:00:00Z'
			})
		).toBe('2015');
		expect(
			formatTimeCoverage({
				temporal_name: 'Temporally Invariant',
				temporal_type: null,
				temporal_start: null,
				temporal_end: null,
				resources: []
			})
		).toBe('Time-invariant');
	});
});

describe('other fields', () => {
	test('spatial coverage', () => {
		expect(formatSpatialCoverage(true, null)).toBe('Global');
		expect(formatSpatialCoverage(false, [-180, -90, 180, 90])).toBe('Global');
		expect(formatSpatialCoverage(false, [-20, -35, 55, 38])).toBe(
			'Regional (longitude -20.0 to 55.0, latitude -35.0 to 38.0)'
		);
	});
	test('added / updated collapses when equal', () => {
		expect(formatAddedUpdated('2017-09-05T00:00:00Z', '2026-05-01T00:00:00Z')).toBe(
			'Sep 2017 / May 2026'
		);
		expect(formatAddedUpdated('2026-05-01T00:00:00Z', '2026-05-20T00:00:00Z')).toBe('May 2026');
	});
});

describe('linkParts', () => {
	test('splits out URLs without their trailing punctuation', () => {
		expect(linkParts('See https://landmarkmap.org/. Thanks')).toEqual([
			{ text: 'See ' },
			{ text: 'https://landmarkmap.org/', href: 'https://landmarkmap.org/' },
			{ text: '. Thanks' }
		]);
		expect(linkParts('no links')).toEqual([{ text: 'no links' }]);
	});
});
