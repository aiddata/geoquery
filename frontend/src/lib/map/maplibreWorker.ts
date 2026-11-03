// MapLibre 6 ships its web worker as a sibling module and, by default, loads it
// from next to maplibre-gl.mjs via import.meta.url. Once Vite pre-bundles or
// chunks maplibre-gl that sibling no longer exists, so hand MapLibre the URL of
// the worker as Vite emits it. Import this module before creating a map.
import { setWorkerUrl } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';

setWorkerUrl(workerUrl);
