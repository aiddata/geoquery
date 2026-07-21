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
	short_name: string | null;
	description: string | null;
	bbox: [number, number, number, number] | null;
	group_name: string | null;
	group_title: string | null;
	group_class: string | null;
	group_level: number | null;
	source_name: string | null;
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
	sort_order: number;
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
	temporal_name: string | null;
	temporal_type: string | null;
	temporal_start: string | null;
	temporal_end: string | null;
	date_updated: string;
	bbox: [number, number, number, number] | null;
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
	extract_types: ExtractType[];
	resources: DatasetResource[];
	filters: Record<string, DatasetFilter> | null;
	outcomes: Record<string, string> | null;
}

export interface DatasetCategory {
	tag: string;
	display: string;
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

export async function fetchDatasetsForFeatures(featureIds: number[]): Promise<DatasetSummary[]> {
	const response = await fetch('/api/datasets/coverage/', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ featureIds }),
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

export interface StoredDataset {
	dataset_name: string;
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
	datasets: RequestDataset[];
	customBoundary?: CustomBoundaryPayload;
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

export async function fetchRequestDetail(id: string): Promise<RequestDetail> {
	const response = await fetch(`/api/analytics/requests/${encodeURIComponent(id)}/`);
	if (!response.ok) {
		throw new Error(`Failed to fetch request: ${response.status}`);
	}
	return response.json();
}

export async function requestHistoryLink(email: string): Promise<void> {
	const response = await fetch('/api/analytics/request-token/', {
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
