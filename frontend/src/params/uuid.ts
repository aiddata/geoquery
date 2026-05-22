import type { ParamMatcher } from '@sveltejs/kit';

export const match: ParamMatcher = (param) =>
	/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(param);
