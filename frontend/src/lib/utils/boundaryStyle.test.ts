import { describe, expect, test } from 'bun:test';
import { assignColorSlots } from './boundaryStyle';

describe('assignColorSlots', () => {
	test('assigns in order from an empty start', () => {
		expect([...assignColorSlots(new Map(), [10, 20, 30])]).toEqual([
			[10, 0],
			[20, 1],
			[30, 2]
		]);
	});

	test('keeps the remaining slots when one is removed', () => {
		const first = assignColorSlots(new Map(), [10, 20, 30]);
		const after = assignColorSlots(first, [20, 30]);
		expect(after.get(20)).toBe(1);
		expect(after.get(30)).toBe(2);
		expect(after.has(10)).toBe(false);
	});

	test('a new set fills a freed slot before any color repeats', () => {
		const first = assignColorSlots(new Map(), [10, 20, 30, 40]);
		const removed = assignColorSlots(first, [10, 30, 40]);
		const added = assignColorSlots(removed, [10, 30, 40, 50]);
		expect(added.get(50)).toBe(1);
	});

	test('past four, each color is used once more before any third time', () => {
		const slots = assignColorSlots(new Map(), [1, 2, 3, 4, 5, 6, 7, 8, 9]);
		const counts = [0, 0, 0, 0];
		for (const slot of slots.values()) counts[slot]++;
		expect(counts).toEqual([3, 2, 2, 2]);
		expect(slots.get(5)).toBe(0);
	});
});
