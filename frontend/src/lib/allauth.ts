/**
 * Client for the django-allauth headless API (browser/session-cookie mode).
 * Endpoint reference: https://docs.allauth.org/en/latest/headless/openapi-specification/
 */
import { apiFetch, ensureCsrfCookie } from '$lib/api';

const BASE = '/api/_allauth/browser/v1';

export interface AllauthUser {
	id: number;
	display: string;
	email: string;
	username?: string;
	has_usable_password?: boolean;
}

export interface EmailAddress {
	email: string;
	verified: boolean;
	primary: boolean;
}

export interface ProviderAccount {
	uid: string;
	display: string;
	provider: { id: string; name: string };
}

export interface AllauthErrorDetail {
	code?: string;
	message: string;
	param?: string;
}

export class AllauthRequestError extends Error {
	constructor(
		public readonly status: number,
		public readonly errors: AllauthErrorDetail[],
		fallbackMessage: string
	) {
		super(errors[0]?.message ?? fallbackMessage);
		this.name = 'AllauthRequestError';
	}
}

export type AuthSession =
	| { status: 'authenticated'; user: AllauthUser }
	| { status: 'anonymous'; pendingFlow: string | null };

export interface ProviderSignupDetails {
	user: AllauthUser;
	account: ProviderAccount;
	email: EmailAddress[];
}

interface AllauthResponse<T> {
	status: number;
	data: T;
}

interface AuthData {
	user?: AllauthUser;
	flows?: { id: string; is_pending?: boolean }[];
}

function isAllauthErrorDetail(value: unknown): value is AllauthErrorDetail {
	return (
		typeof value === 'object' &&
		value !== null &&
		typeof (value as { message?: unknown }).message === 'string'
	);
}

async function requestError(
	response: Response,
	fallbackMessage: string
): Promise<AllauthRequestError> {
	const body = (await response.json().catch(() => null)) as { errors?: unknown } | null;
	const errors = Array.isArray(body?.errors)
		? body.errors.filter(isAllauthErrorDetail)
		: [];
	return new AllauthRequestError(response.status, errors, fallbackMessage);
}

async function parseData<T>(response: Response): Promise<T> {
	let body: unknown;
	try {
		body = await response.json();
	} catch {
		throw new AllauthRequestError(
			response.status,
			[],
			'The sign-in service returned an invalid response.'
		);
	}
	if (typeof body !== 'object' || body === null || !('data' in body)) {
		throw new AllauthRequestError(
			response.status,
			[],
			'The sign-in service returned an incomplete response.'
		);
	}
	return (body as AllauthResponse<T>).data;
}

function pendingFlow(data: AuthData): string | null {
	return data.flows?.find((flow) => flow.is_pending)?.id ?? null;
}

async function parseAuthSession(response: Response): Promise<AuthSession> {
	if (response.status === 410) {
		return { status: 'anonymous', pendingFlow: null };
	}
	if (response.status !== 200 && response.status !== 401) {
		throw await requestError(response, `Session check failed: ${response.status}`);
	}

	const data = await parseData<AuthData>(response);
	if (response.status === 200) {
		if (!data.user) {
			throw new AllauthRequestError(
				response.status,
				[],
				'The sign-in service returned an incomplete session.'
			);
		}
		return { status: 'authenticated', user: data.user };
	}
	return { status: 'anonymous', pendingFlow: pendingFlow(data) };
}

/**
 * Turn the `?error=`/`?error_process=` pair allauth appends to the provider
 * callback URL into something a person can act on.
 *
 * Codes come from two places: `AuthError` in the OAuth2 callback view
 * (`unknown`, `cancelled`, `denied`) and the headless social login flow
 * (`signup_closed`, `permission_denied`, `reauthentication_required`, plus
 * socialaccount adapter validation codes such as `email_taken`).
 */
export function describeAuthError(code: string | null, process: string | null): string {
	const connecting = process === 'connect';

	switch (code) {
		case 'cancelled':
		case 'denied':
			return connecting
				? 'You cancelled the GitHub authorization, so no account was connected.'
				: 'You cancelled the GitHub authorization, so you were not signed in.';
		case 'signup_closed':
			return 'New account registration is currently closed.';
		case 'permission_denied':
			return 'That GitHub account is not permitted to sign in here.';
		case 'reauthentication_required':
			return 'For security, please sign in again before making this change.';
		case 'email_taken':
			return 'An account already exists with this email address. Sign in to that account first, then connect GitHub from your account settings.';
		case 'connected_other':
			return 'That GitHub account is already connected to a different GeoQuery account.';
		case 'no_verified_email':
			return 'Your GitHub account has no verified email address. Verify an email on GitHub, then try again.';
		case 'invalid_token':
			return 'GitHub returned credentials we could not validate. Please try again.';
		case 'unknown':
			return connecting
				? 'Something went wrong while connecting your GitHub account. Please try again — if it keeps happening, contact an administrator.'
				: 'Something went wrong while talking to GitHub, so sign-in could not be completed. Please try again — if it keeps happening, contact an administrator.';
		default:
			return code
				? `Sign-in could not be completed (${code}). Please try again.`
				: 'Sign-in did not complete. Please try again.';
	}
}

/** Read the current session, retaining any pending authentication stage. */
export async function getAuthSession(): Promise<AuthSession> {
	const response = await apiFetch(`${BASE}/auth/session`);
	return parseAuthSession(response);
}

/** Returns the logged-in user, or null when the session is anonymous. */
export async function getSession(): Promise<AllauthUser | null> {
	const session = await getAuthSession();
	return session.status === 'authenticated' ? session.user : null;
}

/** Load the details allauth retained for an incomplete provider signup. */
export async function getProviderSignup(): Promise<ProviderSignupDetails> {
	const response = await apiFetch(`${BASE}/auth/provider/signup`);
	if (!response.ok) {
		throw await requestError(response, `Provider signup check failed: ${response.status}`);
	}
	return parseData<ProviderSignupDetails>(response);
}

/** Supply the missing email and return the resulting auth or pending state. */
export async function submitProviderSignup(email: string): Promise<AuthSession> {
	const response = await apiFetch(`${BASE}/auth/provider/signup`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ email })
	});
	return parseAuthSession(response);
}

/** Ends the session. allauth answers 401 (now anonymous) — that's success. */
export async function logout(): Promise<void> {
	const response = await apiFetch(`${BASE}/auth/session`, { method: 'DELETE' });
	if (!response.ok && response.status !== 401) {
		throw new Error(`Logout failed: ${response.status}`);
	}
}

/**
 * Start the GitHub OAuth flow. Must be a real form POST (not fetch): the
 * response is a 302 to github.com that the browser has to follow.
 */
export async function loginWithGitHub(next: string = '/account'): Promise<void> {
	const token = await ensureCsrfCookie();
	const callback = `${location.origin}/account/provider/callback?next=${encodeURIComponent(next)}`;

	const form = document.createElement('form');
	form.method = 'POST';
	form.action = `${BASE}/auth/provider/redirect`;
	const fields: Record<string, string> = {
		provider: 'github',
		process: 'login',
		callback_url: callback,
		csrfmiddlewaretoken: token
	};
	for (const [name, value] of Object.entries(fields)) {
		const input = document.createElement('input');
		input.type = 'hidden';
		input.name = name;
		input.value = value;
		form.appendChild(input);
	}
	document.body.appendChild(form);
	form.submit();
}

// ── Email management (add + verify secondary addresses to claim history) ──

export async function listEmails(): Promise<EmailAddress[]> {
	const response = await apiFetch(`${BASE}/account/email`);
	if (!response.ok) throw new Error(`Failed to list emails: ${response.status}`);
	return parseData(response);
}

async function emailAction(
	method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
	body: Record<string, unknown>
): Promise<EmailAddress[]> {
	const response = await apiFetch(`${BASE}/account/email`, {
		method,
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!response.ok) {
		const err = await response.json().catch(() => null);
		const message = err?.errors?.[0]?.message ?? `Request failed: ${response.status}`;
		throw new Error(message);
	}
	// PUT (resend verification) returns a bare status object, not the list.
	const parsed = await response.json().catch(() => null);
	return (parsed?.data as EmailAddress[]) ?? [];
}

export const addEmail = (email: string) => emailAction('POST', { email });
export const resendVerification = (email: string) => emailAction('PUT', { email });
export const setPrimaryEmail = (email: string) => emailAction('PATCH', { email, primary: true });
export const removeEmail = (email: string) => emailAction('DELETE', { email });

export async function verifyEmail(key: string): Promise<boolean> {
	const response = await apiFetch(`${BASE}/auth/email/verify`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ key })
	});
	// 200 = verified while logged in; 401 with meta = verified, session state
	// unchanged. Anything else (400 bad key, 409 conflict) is a failure.
	return response.status === 200 || response.status === 401;
}

export async function listProviders(): Promise<ProviderAccount[]> {
	const response = await apiFetch(`${BASE}/account/providers`);
	if (!response.ok) throw new Error(`Failed to list providers: ${response.status}`);
	return parseData(response);
}
