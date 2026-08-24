import { afterEach, describe, expect, mock, test } from 'bun:test';
import {
	AllauthRequestError,
	getAuthSession,
	getProviderSignup,
	submitProviderSignup,
	type AllauthUser
} from '$lib/allauth';

const USER: AllauthUser = {
	id: 7,
	display: 'Octo Cat',
	email: 'octo@example.com',
	username: 'octocat'
};

const originalFetch = globalThis.fetch;
const originalDocument = globalThis.document;

function jsonResponse(status: number, data: unknown): Response {
	return new Response(JSON.stringify({ status, data }), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

function setFetch(handler: typeof fetch): void {
	globalThis.fetch = handler;
}

function setCsrfCookie(): void {
	Object.defineProperty(globalThis, 'document', {
		configurable: true,
		value: { cookie: 'csrftoken=test-token' } as Document
	});
}

afterEach(() => {
	globalThis.fetch = originalFetch;
	Object.defineProperty(globalThis, 'document', {
		configurable: true,
		value: originalDocument
	});
});

describe('getAuthSession', () => {
	test('returns the authenticated user', async () => {
		setFetch(mock(async () => jsonResponse(200, { user: USER })) as unknown as typeof fetch);

		await expect(getAuthSession()).resolves.toEqual({
			status: 'authenticated',
			user: USER
		});
	});

	test('retains the pending provider signup flow', async () => {
		setFetch(
			mock(async () =>
				jsonResponse(401, {
					flows: [
						{ id: 'login' },
						{ id: 'provider_signup', is_pending: true }
					]
				})
			) as unknown as typeof fetch
		);

		await expect(getAuthSession()).resolves.toEqual({
			status: 'anonymous',
			pendingFlow: 'provider_signup'
		});
	});

	test('propagates a rejected fetch', async () => {
		setFetch(
			mock(async () => {
				throw new TypeError('offline');
			}) as unknown as typeof fetch
		);

		await expect(getAuthSession()).rejects.toThrow('offline');
	});

	test('turns an unexpected status into a structured error', async () => {
		setFetch(mock(async () => jsonResponse(500, {})) as unknown as typeof fetch);

		try {
			await getAuthSession();
			throw new Error('Expected getAuthSession to reject');
		} catch (error) {
			expect(error).toBeInstanceOf(AllauthRequestError);
			expect((error as AllauthRequestError).status).toBe(500);
		}
	});
});

describe('provider signup', () => {
	test('loads the provider details and suggested email addresses', async () => {
		const details = {
			user: USER,
			account: {
				uid: '123',
				display: 'octocat',
				provider: { id: 'github', name: 'GitHub' }
			},
			email: [{ email: USER.email, verified: true, primary: true }]
		};
		setFetch(mock(async () => jsonResponse(200, details)) as unknown as typeof fetch);

		await expect(getProviderSignup()).resolves.toEqual(details);
	});

	test('returns the authenticated user when signup completes immediately', async () => {
		setCsrfCookie();
		setFetch(mock(async () => jsonResponse(200, { user: USER })) as unknown as typeof fetch);

		await expect(submitProviderSignup(USER.email)).resolves.toEqual({
			status: 'authenticated',
			user: USER
		});
	});

	test('submits the email and returns the next pending flow', async () => {
		setCsrfCookie();
		setFetch(
			mock(async (input, init) => {
				expect(input).toBe('/api/_allauth/browser/v1/auth/provider/signup');
				expect(init?.method).toBe('POST');
				expect(new Headers(init?.headers).get('X-CSRFToken')).toBe('test-token');
				expect(JSON.parse(init?.body as string)).toEqual({ email: USER.email });
				return jsonResponse(401, {
					flows: [{ id: 'verify_email', is_pending: true }]
				});
			}) as unknown as typeof fetch
		);

		await expect(submitProviderSignup(USER.email)).resolves.toEqual({
			status: 'anonymous',
			pendingFlow: 'verify_email'
		});
	});

	test('preserves allauth email validation details', async () => {
		setCsrfCookie();
		setFetch(
			mock(async () =>
				new Response(
					JSON.stringify({
						status: 400,
						errors: [
							{
								code: 'email_taken',
								message: 'An account already uses this email.',
								param: 'email'
							}
						]
					}),
					{ status: 400, headers: { 'Content-Type': 'application/json' } }
				)
			) as unknown as typeof fetch
		);

		try {
			await submitProviderSignup(USER.email);
			throw new Error('Expected submitProviderSignup to reject');
		} catch (error) {
			expect(error).toBeInstanceOf(AllauthRequestError);
			const requestError = error as AllauthRequestError;
			expect(requestError.status).toBe(400);
			expect(requestError.errors[0]).toEqual({
				code: 'email_taken',
				message: 'An account already uses this email.',
				param: 'email'
			});
		}
	});
});
