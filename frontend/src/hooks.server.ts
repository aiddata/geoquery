import { redirect } from '@sveltejs/kit';
import { maintenance } from '$lib/config/status';
import type { Handle } from '@sveltejs/kit';

export const handle: Handle = async ({ event, resolve }) => {
	if (maintenance.enabled && event.url.pathname !== '/maintenance') {
		redirect(307, '/maintenance');
	}
	return resolve(event);
};