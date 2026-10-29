import { describe, expect, test } from 'bun:test';
import { unionBbox } from './bbox';

describe('unionBbox', () => {
	test('covers every bbox', () => {
		expect(
			unionBbox([
				[0, 0, 10, 10],
				[-5, 2, 3, 20]
			])
		).toEqual([-5, 0, 10, 20]);
	});

	test('skips missing bboxes', () => {
		expect(unionBbox([null, [1, 2, 3, 4], undefined])).toEqual([1, 2, 3, 4]);
	});

	test('is null when nothing is given', () => {
		expect(unionBbox([])).toBeNull();
		expect(unionBbox([null])).toBeNull();
	});
});
