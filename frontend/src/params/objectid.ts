import type { ParamMatcher } from '@sveltejs/kit';

/**
 * A 24-character hex Mongo ObjectId, as carried by imported legacy requests.
 *
 * Keeps `legacy/[id]` from matching arbitrary junk and rendering a detail page
 * that can only fail. Mirrors `uuid.ts`, and the same constraint the backend
 * applies to the detail route's `pk`.
 *
 * The page lives at `/legacy/<id>` rather than under `/requests/`, because the
 * download host claims everything below `/requests/legacy/`: the page worked
 * on an in-app click but 404ed on refresh, since only a full page load reaches
 * the server. Zips are nested as `<id>/<id>.zip`, mirroring current requests,
 * so a one-segment page URL and a nested file URL stay distinguishable.
 */
export const match: ParamMatcher = (param) => /^[0-9a-f]{24}$/i.test(param);
