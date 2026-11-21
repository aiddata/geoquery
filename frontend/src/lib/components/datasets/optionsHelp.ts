// Section text shared by raster and feature dataset options, so both read the same.

export const SPLIT_SUMMARY = 'Each value you select gets its own column in your results.';

export const SPLIT_HELP =
	'Each feature gets a separate column for every value you select, for example one column per year. ' +
	'With more than one split or measure, there is a column for every combination. Unselected values are left out. ' +
	'Shift-click to select a range of values.';

/** A required option card with nothing chosen in it (GEO-163), with MissingNote under its title. */
export const MISSING_CARD = 'border-destructive ring-1 ring-destructive';
