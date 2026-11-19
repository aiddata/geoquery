// ── Fetch helpers ───────────────────────────────────────────────

function getCookie(name: string): string | null {
	const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
	return match ? decodeURIComponent(match[1]) : null;
}

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * Return the CSRF token, bootstrapping the cookie from the backend if needed.
 * Django requires X-CSRFToken on unsafe methods for session-authenticated
 * requests (logged-in submissions, allauth headless calls).
 */
export async function ensureCsrfCookie(): Promise<string> {
	let token = getCookie('csrftoken');
	if (!token) {
		await fetch('/api/auth/csrf/');
		token = getCookie('csrftoken') ?? '';
	}
	return token;
}

/** fetch that attaches the CSRF header on unsafe methods and sends cookies. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
	const method = (init.method ?? 'GET').toUpperCase();
	const headers = new Headers(init.headers);
	if (UNSAFE_METHODS.has(method)) {
		headers.set('X-CSRFToken', await ensureCsrfCookie());
	}
	return fetch(path, { ...init, headers, credentials: 'same-origin' });
}

// ── Config ──────────────────────────────────────────────────────

export interface AppConfig {
	protomaps_api_key: string;
	/** Features limited to beta testers (see #lib/stores/features). */
	beta_features: string[];
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
	short_name: string | null;
	description: string | null;
	bbox: [number, number, number, number] | null;
	group_name: string | null;
	group_title: string | null;
	group_class: string | null;
	group_level: number | null;
	source_name: string | null;
	source_url: string | null;
	// GeoQuery redistributes this data under its original terms, so the
	// licence travels with every record that describes a boundary.
	license: string | null;
	license_url: string | null;
	citation: string | null;
	tags: string[];
	date_added: string | null;
}

export interface BoundaryPreset {
	name: string;
	description?: string | null;
	source_name?: string | null;
	group_class?: string | null;
	group_level?: number | null;
	tags: string[];
	/** At least one of these tags */
	any_tags?: string[];
	/** None of these tags */
	exclude_tags?: string[];
	/** Other names the boundary search matches */
	aliases?: string[];
	/** List presets: exact boundary set names (rule fields are then ignored) */
	members?: string[] | null;
	sort_order: number;
}

/** Ids of the boundary sets with a feature inside a [west, south, east, north] box. */
export async function intersectingBoundaryIds(bbox: [number, number, number, number]): Promise<number[]> {
	const response = await fetch(`/api/features/intersecting/?bbox=${bbox.map((v) => v.toFixed(5)).join(',')}`);
	if (!response.ok) throw new Error(`Area lookup failed: ${response.status}`);
	return (await response.json()).ids;
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

export async function fetchBoundaryPresets(): Promise<BoundaryPreset[]> {
	const response = await fetch('/api/features/presets/');
	if (!response.ok) {
		throw new Error(`Failed to fetch presets: ${response.status}`);
	}
	return response.json();
}

export function boundaryTileUrl(boundaryName: string): string {
	const base = typeof window !== 'undefined' ? window.location.origin : '';
	return `${base}/api/features/tiles/${boundaryName}/{z}/{x}/{y}.mvt`;
}

/** MVT layer name of the multi-collection tiles (MULTI_TILE_LAYER in backend/features/views.py). */
export const MULTI_TILE_LAYER = 'boundaries';

/**
 * MVT layer of point clusters on both boundary tile endpoints (CLUSTER_TILE_LAYER in
 * backend/features/views.py). Where a selection is too dense to draw, its tiles up to
 * the clusters' maximum zoom hold this instead of polygons: points carrying `count`,
 * the features in all, and fc_<id>, each boundary's share.
 */
export const CLUSTER_TILE_LAYER = 'clusters';

/**
 * Tiles holding several boundaries in one layer, each feature tagged with its `fc_id`.
 * Ids are sorted and deduplicated so a selection always maps to the same URL.
 */
export function multiBoundaryTileUrl(fcIds: number[]): string {
	const base = typeof window !== 'undefined' ? window.location.origin : '';
	const ids = [...new Set(fcIds)].sort((a, b) => a - b);
	return `${base}/api/features/multitiles/{z}/{x}/{y}.mvt?fc=${ids.join(',')}`;
}

// ── Dataset types ──────────────────────────────────────────────

export interface DatasetSummary {
	id: number;
	name: string;
	title: string | null;
	description: string | null;
	type: string;
	processing_class: string;
	tags: string[];
	source_name: string | null;
	source_url: string | null;
	// See BoundaryResult: licence and citation ride along with the source.
	license: string | null;
	license_url: string | null;
	citation: string | null;
	temporal_name: string | null;
	temporal_type: string | null;
	temporal_start: string | null;
	temporal_end: string | null;
	date_updated: string;
	bbox: [number, number, number, number] | null;
	/** From the coverage endpoint when boundary sets were given: the selected
	 *  boundary set ids this dataset covers (GEO-127). */
	covered_boundary_sets?: number[];
}

export interface DatasetResource {
	id: number;
	name: string;
	label: string | null;
	path: string;
	temporal: string | null;
}

export interface ExtractType {
	short_name: string;
	description: string | null;
}

export interface RangeFilter {
	type: 'range';
	display?: string;
	aggregate?: boolean;
	min: number;
	max: number;
}

export interface CategoricalFilter {
	type: 'categorical';
	display?: string;
	aggregate?: boolean;
	categories: string[];
}

export type DatasetFilter = RangeFilter | CategoricalFilter;

export interface DatasetDetail extends DatasetSummary {
	date_added: string;
	details: string | null;
	/** What a value means, with units: "distance in meters". */
	variable_description: string | null;
	is_global: boolean;
	/** Cell size in decimal degrees; null when not recorded. */
	resolution: number | null;
	version: string | null;
	extract_types: ExtractType[];
	resources: DatasetResource[];
	filters: Record<string, DatasetFilter> | null;
	outcomes: Record<string, string> | null;
}

export interface DatasetCategory {
	/** Stable key for the category */
	tag: string;
	display: string;
	/** Dataset tags that put a dataset in this category (any one is enough) */
	tags: string[];
}

// ── Features API ───────────────────────────────────────────────

export async function fetchFeatureIds(fcIds: number[]): Promise<number[]> {
	const params = new URLSearchParams({ fc: fcIds.join(',') });
	const response = await fetch(`/api/features/ids/?${params}`);
	if (!response.ok) {
		throw new Error(`Failed to fetch feature IDs: ${response.status}`);
	}
	const data = await response.json();
	return data.featureIds as number[];
}

// ── Dataset API ────────────────────────────────────────────────

/**
 * Datasets covering the selected features. With fcIds (the selected boundary
 * sets), each dataset also says which of those sets it covers.
 */
export async function fetchDatasetsForFeatures(featureIds: number[], fcIds?: number[]): Promise<DatasetSummary[]> {
	// Must go through apiFetch: this endpoint authenticates the session so that
	// catalog-granted datasets are included, and DRF then enforces CSRF on it
	// for logged-in users. A bare fetch 403s once you sign in.
	const response = await apiFetch('/api/datasets/coverage/', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(fcIds ? { featureIds, fcIds } : { featureIds }),
	});
	if (!response.ok) {
		throw new Error(`Failed to fetch datasets: ${response.status}`);
	}
	return response.json();
}

export async function fetchAllDatasets(): Promise<DatasetSummary[]> {
	const response = await fetch('/api/datasets/');
	if (!response.ok) {
		throw new Error(`Failed to fetch datasets: ${response.status}`);
	}
	return response.json();
}

export async function fetchDatasetDetail(datasetName: string): Promise<DatasetDetail> {
	const response = await fetch(`/api/datasets/${encodeURIComponent(datasetName)}/`);
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

export interface RequestDataset {
	datasetName: string;
	datasetType: string;
	extractTypes?: string[];
	resources?: string[];
	resourceLabels?: string[];
	kwargs?: Record<string, unknown>;
}

export interface SubmittedRequest {
	id: string;
	name: string | null;
	status: number;
	status_label: string;
	submit_time: string;
	task_count: number | null;
	warnings?: string[];
}

export interface PastRequest {
	id: string;
	name: string | null;
	status: number;
	status_label: string;
	submit_time: string;
}

/** A completed request imported from the previous version of GeoQuery. */
export interface LegacyPastRequest {
	id: string;
	name: string | null;
	submit_time: string;
	complete_time: string;
	dataset_count: number;
	status_label: 'completed';
	is_legacy: true;
}

export interface LegacyRequestDetail extends LegacyPastRequest {
	boundary_title: string;
	boundary_name: string;
	boundary_group: string;
	dataset_titles: string[];
	/** Absent until the archive base URL is configured. */
	download_url?: string;
}

export interface StoredDataset {
	dataset_name: string;
	/** Feature datasets: the version's name (its output column prefix) */
	name?: string | null;
	dataset_type: string | null;
	extract_types?: string[];
	resources?: string[];
	resource_labels?: string[];
	kwargs?: Record<string, unknown>;
}

export interface RequestDetailData {
	selection_label: string | null;
	selection_detail: string | null;
	feature_ids: number[];
	datasets: StoredDataset[];
	is_custom_boundary?: boolean;
	boundary_operations?: { id: string; type: string; params: Record<string, unknown> }[];
}

export interface RequestDetail extends PastRequest {
	complete_time: string | null;
	task_count: number;
	data: RequestDetailData;
	download_url?: string;
	documentation_url?: string;
	visualization_url?: string;
}

export interface CustomBoundaryPayload {
	features: object;
	operations: { id: string; type: string; params: Record<string, unknown> }[];
	fileName: string;
	featureCount: number;
}

export async function submitRequest(payload: {
	name: string;
	email: string;
	selectionLabel?: string;
	selectionDetail?: string;
	featureIds: number[];
	/** The boundary sets picked, so the request can be used as a template later */
	fcIds?: number[];
	datasets: RequestDataset[];
	customBoundary?: CustomBoundaryPayload;
}): Promise<SubmittedRequest> {
	const response = await apiFetch('/api/analytics/requests/', {
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

export async function fetchRequestDetail(id: string): Promise<RequestDetail> {
	const response = await fetch(`/api/analytics/requests/${encodeURIComponent(id)}/`);
	if (!response.ok) {
		throw new Error(`Failed to fetch request: ${response.status}`);
	}
	return response.json();
}

export async function requestHistoryLink(email: string): Promise<void> {
	const response = await apiFetch('/api/analytics/request-token/', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ email })
	});
	if (!response.ok) {
		const err = await response.json().catch(() => ({}));
		throw new Error(err.error || `Failed to send link: ${response.status}`);
	}
}

// ── Visualization ──────────────────────────────────────────────

export interface VisualizationFeature {
	name: string;
	fc: string;
	[column: string]: string | number | null;
}

// Fields shared by both request viz and explore viz payloads.
export interface VizPayload {
	fc_names: string[];
	columns: string[];
	col_groups: Record<string, string[]>;
	col_descriptions: Record<string, string>;
	col_filter_desc?: Record<string, string>;
	col_dataset_titles: Record<string, string>;
	col_temporal: Record<string, string>;
	features: Record<string, VisualizationFeature>;
	bbox: [number, number, number, number] | null;
}

export interface VisualizationData extends VizPayload {
	request_id: string;
	request_name: string;
	selection_label: string;
	request_status: number | null;
}

export async function fetchVisualizationData(requestId: string): Promise<VisualizationData> {
	const response = await fetch(`/api/visualize/request/${encodeURIComponent(requestId)}/`);
	if (!response.ok) {
		throw new Error(`Failed to fetch visualization data: ${response.status}`);
	}
	return response.json();
}

// ── Explore viz ──────────────────────────────────────────────────

export interface ExploreOption {
	po_id: number;
	short_name: string;
	description: string;
}

export interface ExploreDataset {
	dataset_id: number;
	dataset_name: string;
	dataset_title: string;
	options: ExploreOption[];
}

export async function fetchExploreAvailable(fcIds: number[]): Promise<ExploreDataset[]> {
	const response = await fetch(`/api/visualize/explore/available/?fc=${fcIds.join(',')}`);
	if (!response.ok) throw new Error(`Failed to fetch available options: ${response.status}`);
	return response.json();
}

export async function fetchExploreData(fcIds: number[], poIds: number[]): Promise<VizPayload> {
	const response = await fetch(
		`/api/visualize/explore/?fc=${fcIds.join(',')}&po=${poIds.join(',')}`
	);
	if (!response.ok) throw new Error(`Failed to fetch explore data: ${response.status}`);
	return response.json();
}

export async function fetchMyRequests(): Promise<PastRequest[]> {
	const response = await apiFetch('/api/analytics/my-requests/');
	if (!response.ok) {
		throw new Error(`Failed to fetch requests: ${response.status}`);
	}
	return response.json();
}

export async function fetchRequestsByToken(token: string): Promise<PastRequest[]> {
	const response = await fetch(`/api/analytics/history/${encodeURIComponent(token)}/`);
	if (response.status === 410) {
		throw new Error('expired');
	}
	if (!response.ok) {
		throw new Error('invalid');
	}
	return response.json();
}

export async function fetchMyLegacyRequests(): Promise<LegacyPastRequest[]> {
	const response = await apiFetch('/api/analytics/legacy-requests/');
	if (!response.ok) {
		throw new Error(`Failed to fetch legacy requests: ${response.status}`);
	}
	return response.json();
}

export async function fetchLegacyRequestsByToken(token: string): Promise<LegacyPastRequest[]> {
	const response = await fetch(`/api/analytics/legacy-history/${encodeURIComponent(token)}/`);
	if (response.status === 410) {
		throw new Error('expired');
	}
	if (!response.ok) {
		throw new Error('invalid');
	}
	return response.json();
}

export async function fetchLegacyRequestDetail(id: string): Promise<LegacyRequestDetail> {
	const response = await fetch(`/api/analytics/legacy-requests/${encodeURIComponent(id)}/`);
	if (!response.ok) {
		throw new Error(`Failed to fetch legacy request: ${response.status}`);
	}
	return response.json();
}

// ── Stats ───────────────────────────────────────────────────────

export interface StatsPoint {
	date: string;
	count: number;
}

export interface Stats {
	total: number;
	status_counts: { completed: number; pending: number; processing: number; error: number };
	extract_counts: {
		completed: number;
		pending: number;
		claimed: number;
		processing: number;
		error: number;
		total: number;
	};
	time_series: Record<'submit_time' | 'complete_time', Record<string, StatsPoint[]>>;
	extract_time_series: Record<string, StatsPoint[]>;
	/** Requests imported from the previous version of GeoQuery. */
	/** Absent from snapshots written before this field shipped: the endpoint
	 * serves a file, and STATS_REPORT_INTERVAL_SECONDS=0 disables the rebuild
	 * entirely, so a stale snapshot can persist indefinitely. */
	legacy_request_count?: number;
	// The fields below are absent from snapshots written before they shipped.
	datasets_available?: number;
	boundary_sets_available?: number;
	/** Features (areas) across the available boundary sets. */
	boundary_features_available?: number;
	/** Distinct requester emails, and their email domains (organizations),
	 * across current requests and those from earlier versions. */
	users?: number;
	organizations?: number;
	/** Requests from earlier versions, in the same shape as `time_series`. */
	legacy_time_series?: Record<'submit_time' | 'complete_time', Record<string, StatsPoint[]>>;
	/** Day (YYYY-MM-DD) of the current system's first request. */
	cutover?: string | null;
	/** Submit-to-complete time over requests completed in the last `days` days. */
	turnaround?: { days: number; count: number; median_seconds: number | null; p90_seconds: number | null };
	/** Public datasets and boundary sets in the most requests, current GeoQuery only. */
	top_datasets?: { name: string; title: string; requests: number }[];
	top_boundary_sets?: { id: number; title: string; requests: number }[];
	generated_at: string;
}

export interface ServiceStatus {
	state: 'healthy' | 'backlogged' | 'delayed';
	unfinished_requests: number;
	oldest_wait_seconds: number;
	backlog_after_seconds: number;
	snapshot_age_seconds: number | null;
	checked_at: string;
}

/** Live service status: a cheap per-call check, unlike the snapshot. */
export async function fetchServiceStatus(): Promise<ServiceStatus> {
	const response = await fetch('/api/stats/status/');
	if (!response.ok) {
		throw new Error(`Failed to fetch status: ${response.status}`);
	}
	return response.json();
}

/**
 * Fetch the statistics snapshot.
 *
 * This is a file read on the backend, not a query. The counts are rebuilt every
 * 5 minutes by a scheduled task, deliberately: computing them per request meant
 * aggregating ~280M rows, which took ~16s and took the page down under any
 * concurrency.
 */
export async function fetchStats(): Promise<Stats> {
	const response = await fetch('/api/stats/');
	if (!response.ok) {
		throw new Error(`Failed to fetch stats: ${response.status}`);
	}
	return response.json();
}

/** What a past request asked for that no longer applies (GEO-126). */
export interface RecipeDropped {
	/** Features that weren't part of a whole boundary set */
	features: number;
	datasets: { name: string; title: string; reason: 'unavailable' | 'not_covered' | 'options_removed' }[];
	/** Rasters kept with some of their measures or periods removed */
	options: { name: string; title: string; measures: string[]; periods: string[] }[];
}

export interface RequestRecipeResult {
	/** A request recipe (lib/recipe.ts); checked with parseRecipe before use */
	recipe: unknown;
	boundary_sets: { id: number; name: string; title: string | null; short_name: string | null; bbox: [number, number, number, number] | null }[];
	dropped: RecipeDropped;
}

/** A past request as a recipe, for "Use as template". */
export async function fetchRequestRecipe(id: string): Promise<RequestRecipeResult> {
	const response = await fetch(`/api/analytics/requests/${id}/recipe/`);
	if (!response.ok) {
		const body = await response.json().catch(() => null);
		throw new Error(body?.error ?? `Failed to load the request: ${response.status}`);
	}
	return response.json();
}
