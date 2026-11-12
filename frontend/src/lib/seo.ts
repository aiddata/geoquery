/** The production origin. Canonical and Open Graph URLs always point here. */
export const SITE_URL = 'https://geoquery.aiddata.wm.edu';

export const SITE_NAME = 'AidData GeoQuery';

export const DEFAULT_DESCRIPTION =
	'Free geospatial data extraction from AidData. Pick administrative boundaries for any ' +
	'country, choose from dozens of datasets such as population, nighttime lights, climate, ' +
	'land cover, conflict and malaria, and download them aggregated to each boundary as a CSV.';

/** Paths listed in /sitemap.xml: public pages that make sense to land on. */
export const SITEMAP_PATHS = ['/', '/stats'];

/** schema.org description of the app, for the home page's JSON-LD. */
export const APP_JSON_LD = {
	'@context': 'https://schema.org',
	'@type': 'WebApplication',
	name: SITE_NAME,
	url: SITE_URL + '/',
	description: DEFAULT_DESCRIPTION,
	applicationCategory: 'ReferenceApplication',
	operatingSystem: 'Any',
	isAccessibleForFree: true,
	offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
	publisher: { '@type': 'Organization', name: 'AidData', url: 'https://www.aiddata.org' },
	sameAs: ['https://www.aiddata.org/geoquery', 'https://docs.geoquery.org/']
};
