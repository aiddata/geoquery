// ── Config ──────────────────────────────────────────────────────

export interface AppConfig {
	protomaps_api_key: string;
}

let _configPromise: Promise<AppConfig> | null = null;

export function fetchConfig(): Promise<AppConfig> {
	if (!_configPromise) {
		_configPromise = fetch('/api/config/')
			.then((r) => {
				if (!r.ok) throw new Error(`Config request failed: ${r.status}`);
				return r.json();
			});
	}
	return _configPromise;
}

// ── Boundaries ──────────────────────────────────────────────────

export interface BoundaryResult {
	id: number;
	name: string;
	title: string | null;
	description: string | null;
	bbox: [number, number, number, number] | null;
}

export async function searchBoundaries(
	query: string,
	limit: number = 10
): Promise<BoundaryResult[]> {
	const params = new URLSearchParams();
	if (query) params.set('q', query);
	params.set('limit', String(limit));

	const response = await fetch(`/api/features/autocomplete/?${params}`);
	if (!response.ok) {
		throw new Error(`Autocomplete request failed: ${response.status}`);
	}
	return response.json();
}

export function boundaryTileUrl(boundaryName: string): string {
	const base = typeof window !== 'undefined' ? window.location.origin : '';
	return `${base}/api/features/tiles/${boundaryName}/{z}/{x}/{y}.mvt`;
}

// ── Dataset types ──────────────────────────────────────────────

export interface DatasetSummary {
	id: number;
	name: string;
	title: string | null;
	description: string | null;
	type: string; // "raster" | "release"
	tags: string[];
	source_name: string | null;
	source_url: string | null;
	temporal_name: string | null;
	temporal_type: string | null;
	temporal_start: string | null;
	temporal_end: string | null;
	date_updated: string;
}

export interface DatasetResource {
	id: number;
	name: string;
	label: string | null;
	path: string;
	temporal: string | null;
}

export interface DatasetField {
	name: string;
	display: string;
	type: 'list' | 'slider';
	is_default: boolean;
	distinct: string[] | [number, number];
}

export interface ExtractType {
	short_name: string;
	description: string | null;
}

export interface DatasetDetail extends DatasetSummary {
	// raster datasets
	extract_types: ExtractType[];
	resources: DatasetResource[];
	// release datasets
	fields: Record<string, DatasetField>;
}

export interface DatasetCategory {
	tag: string;
	display: string;
}

// ── Dataset API stubs ──────────────────────────────────────────
// These call endpoints that don't exist yet on the backend.

export async function fetchDatasetsForBoundary(boundaryName: string): Promise<DatasetSummary[]> {
	const params = new URLSearchParams({ boundary: boundaryName });
	const response = await fetch(`/api/datasets/?${params}`);
	if (!response.ok) {
		throw new Error(`Failed to fetch datasets: ${response.status}`);
	}
	return response.json();
}

export async function fetchDatasetDetail(
	datasetName: string,
	boundaryName: string
): Promise<DatasetDetail> {
	const params = new URLSearchParams({ boundary: boundaryName });
	const response = await fetch(`/api/datasets/${encodeURIComponent(datasetName)}/?${params}`);
	if (!response.ok) {
		throw new Error(`Failed to fetch dataset detail: ${response.status}`);
	}
	return response.json();
}

export async function fetchDatasetCategories(): Promise<DatasetCategory[]> {
	const response = await fetch('/api/datasets/categories/');
	if (!response.ok) {
		throw new Error(`Failed to fetch categories: ${response.status}`);
	}
	return response.json();
}

// ── Requests ───────────────────────────────────────────────────

export interface RequestItem {
	boundaryName: string;
	datasetName: string;
	datasetType: string;
	extractTypes?: string[];
	resources?: string[];
	filters?: Record<string, string[]>;
}

export interface SubmittedRequest {
	id: string;
	name: string | null;
	status: number;
	status_label: string;
	submit_time: string;
	task_count: number;
	warnings?: string[];
}

export interface PastRequest {
	id: string;
	name: string | null;
	status: number;
	status_label: string;
	submit_time: string;
}

export async function submitRequest(payload: {
	name: string;
	email: string;
	items: RequestItem[];
}): Promise<SubmittedRequest> {
	const response = await fetch('/api/analytics/requests/', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
	if (!response.ok) {
		const err = await response.json().catch(() => ({}));
		throw new Error(err.error || `Request submission failed: ${response.status}`);
	}
	return response.json();
}

export async function fetchRequestsByEmail(email: string): Promise<PastRequest[]> {
	const params = new URLSearchParams({ email });
	const response = await fetch(`/api/analytics/requests/?${params}`);
	if (!response.ok) {
		throw new Error(`Failed to fetch requests: ${response.status}`);
	}
	return response.json();
}
