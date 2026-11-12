import { SITE_URL, SITEMAP_PATHS } from '#lib/seo.js';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = () => {
	const urls = SITEMAP_PATHS.map((path) => `\t<url><loc>${SITE_URL}${path}</loc></url>`).join('\n');
	const body = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls}
</urlset>
`;
	return new Response(body, {
		headers: {
			'Content-Type': 'application/xml',
			'Cache-Control': 'public, max-age=3600'
		}
	});
};
