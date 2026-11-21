import { describe, expect, test } from 'bun:test';
import { compactPeriods, formatPeriod, periodRange, periodUnit } from './periods.js';

describe('formatPeriod', () => {
	test('months and days read as dates', () => {
		expect(formatPeriod('199501')).toBe('1995 January');
		expect(formatPeriod('202212')).toBe('2022 December');
		expect(formatPeriod('19950115')).toBe('1995-01-15');
	});
	test('years and anything else are unchanged', () => {
		expect(formatPeriod('2010')).toBe('2010');
		expect(formatPeriod('199513')).toBe('199513');
		expect(formatPeriod('2010-2015')).toBe('2010-2015');
	});
});

describe('periodRange', () => {
	test('years join with a dash, months with a spaced dash', () => {
		expect(periodRange(['1992', '2000', '2013'])).toBe('1992–2013');
		expect(periodRange(['190101', '202212'])).toBe('1901 January – 2022 December');
		expect(periodRange(['2010'])).toBe('2010');
		expect(periodRange([])).toBeNull();
	});
});

describe('compactPeriods', () => {
	test('consecutive runs become one range', () => {
		expect(compactPeriods(['2010', '2011', '2012'])).toEqual(['2010–2012']);
		expect(compactPeriods(['199511', '199512', '199601'])).toEqual(['1995 November – 1996 January']);
	});
	test('gaps keep each period, formatted', () => {
		expect(compactPeriods(['199501', '199503', '199504'])).toEqual(['1995 January', '1995 March', '1995 April']);
		expect(compactPeriods(['2010', '2012', '2013'])).toEqual(['2010', '2012', '2013']);
	});
});

test('periodUnit', () => {
	expect(periodUnit(['2010', '2011'])).toEqual(['year', 'years']);
	expect(periodUnit(['199501'])).toEqual(['month', 'months']);
	expect(periodUnit(['2010', '199501'])).toEqual(['time period', 'time periods']);
});
