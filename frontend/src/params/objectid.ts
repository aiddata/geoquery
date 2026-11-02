import type { ParamMatcher } from '@sveltejs/kit';

/**
 * A 24-character hex Mongo ObjectId, as carried by imported legacy requests.
 *
 * Without this, `requests/legacy/[id]` matches anything in that position —
 * including the download URL `requests/legacy/<id>.zip`, which lives under
 * the same prefix on the download host. A same-origin click on that link is
 * intercepted by the client router, matched to this route with
 * `id = "<id>.zip"`, and turned into a request for
 * `/api/analytics/legacy-requests/<id>.zip/` instead of a download.
 *
 * Mirrors `uuid.ts`, and the same constraint the backend applies to the
 * detail route's `pk`.
 */
export const match: ParamMatcher = (param) => /^[0-9a-f]{24}$/i.test(param);
