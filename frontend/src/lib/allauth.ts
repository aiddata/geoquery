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

interface AllauthResponse<T> {
	status: number;
	data: T;
}

async function parseData<T>(response: Response): Promise<T> {
	const body = (await response.json()) as AllauthResponse<T>;
	return body.data;
}

/** Returns the logged-in user, or null when the session is anonymous. */
export async function getSession(): Promise<AllauthUser | null> {
	const response = await apiFetch(`${BASE}/auth/session`);
	if (response.status === 401 || response.status === 410) return null;
	if (!response.ok) throw new Error(`Session check failed: ${response.status}`);
	const body = (await response.json()) as AllauthResponse<{ user: AllauthUser }>;
	return body.data.user;
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
