/**
 * Site status configuration.
 *
 * banner   — shows a slim notification bar at the top of every page.
 * maintenance — redirects all routes to the /maintenance page.
 *
 * Edit this file to change messages or toggle either feature on/off.
 */

export const banner = {
	/** Set to true to display the status banner. */
	enabled: false,
	/** 'info' (blue) | 'warning' (yellow) | 'error' (red) */
	type: 'info' as 'info' | 'warning' | 'error',
	message: 'GeoQuery is currently undergoing scheduled maintenance. Some features may be unavailable.',
};

export const maintenance = {
	/** Set to true to take the site offline and show the maintenance page. */
	enabled: false,
	heading: 'Down for Maintenance',
	message:
		'GeoQuery is temporarily unavailable while we perform scheduled maintenance. Please check back soon.',
	/** Optional — leave empty to hide. Example: "June 5, 2026 at 14:00 UTC" */
	estimatedReturn: '',
};
