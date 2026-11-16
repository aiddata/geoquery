import { writable } from 'svelte/store';

/**
 * What's been entered on the Review & Submit step, kept as the user moves
 * between the steps and back, like the selection and the cart. In memory
 * for the page session, as they are.
 *
 * - name: null until the step is first opened, which fills in a default.
 * - email: what an anonymous user typed. A signed-in user submits under
 *   their account email, which isn't stored here. Kept after a submit, so a
 *   second request needn't retype it.
 * - boundaryConsent: the custom-boundary consent checkbox.
 */
export interface RequestForm {
	name: string | null;
	email: string;
	boundaryConsent: boolean;
}

function createRequestFormStore() {
	const { subscribe, set, update } = writable<RequestForm>({
		name: null,
		email: '',
		boundaryConsent: false
	});
	return {
		subscribe,
		set,
		update,
		/** After a submit: a fresh name and consent next time; the email stays. */
		resetAfterSubmit: () => update((f) => ({ ...f, name: null, boundaryConsent: false }))
	};
}

export const requestForm = createRequestFormStore();
