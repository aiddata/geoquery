TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GeoQuery – Visualization</title>
  <link rel="stylesheet" href="https://unpkg.com/maplibre-gl@5/dist/maplibre-gl.css" />
  <script src="https://unpkg.com/maplibre-gl@5/dist/maplibre-gl.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@protomaps/basemaps@5.7.0/dist/basemaps.js"></script>
  <script src="https://unpkg.com/simple-statistics@7/dist/simple-statistics.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 13px;
      background: #f8fafc;
      display: flex;
      flex-direction: column;
      height: 100vh;
      color: #1e293b;
    }

    /* ── Header ── */
    #header {
      padding: 10px 16px;
      background: #fff;
      border-bottom: 1px solid #e2e8f0;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
      gap: 12px;
    }
    #header h1 { font-size: 14px; font-weight: 600; color: #0f172a; }
    #header .subtitle { font-size: 12px; color: #64748b; margin-top: 1px; }
    .badge {
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      border-radius: 4px;
      padding: 2px 8px;
      font-size: 11px;
      color: #475569;
      white-space: nowrap;
      flex-shrink: 0;
    }

    /* ── Layout ── */
    #app { display: flex; flex: 1; overflow: hidden; }

    #sidebar {
      width: 264px;
      flex-shrink: 0;
      background: #fff;
      border-right: 1px solid #e2e8f0;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
    }

    .panel {
      padding: 12px 14px;
      border-bottom: 1px solid #f1f5f9;
      flex-shrink: 0;
    }
    .panel-title {
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: #94a3b8;
      margin-bottom: 7px;
    }

    /* ── Select controls ── */
    select {
      width: 100%;
      padding: 6px 28px 6px 8px;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      font-size: 12px;
      color: #1e293b;
      background: #f8fafc;
      cursor: pointer;
      appearance: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2.5'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 8px center;
    }
    select:focus { outline: none; border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59,130,246,0.12); }

    /* ── Legend ── */
    .legend-item { display: flex; align-items: center; gap: 8px; margin-bottom: 5px; font-size: 11px; color: #475569; }
    .legend-swatch { width: 13px; height: 13px; border-radius: 2px; flex-shrink: 0; border: 1px solid rgba(0,0,0,0.08); }

    /* ── Stats ── */
    .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
    .stat-item { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 7px 8px; }
    .stat-label { font-size: 10px; color: #94a3b8; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; }
    .stat-value { font-size: 13px; font-weight: 600; color: #0f172a; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

    /* ── Toggle items (FC + feature checkboxes) ── */
    .toggle-item {
      display: flex;
      align-items: center;
      gap: 7px;
      padding: 3px 2px;
      cursor: pointer;
      font-size: 12px;
      color: #1e293b;
      border-radius: 4px;
      user-select: none;
    }
    .toggle-item:hover { background: #f8fafc; }
    .toggle-item input[type="checkbox"] { flex-shrink: 0; cursor: pointer; accent-color: #3b82f6; width: 13px; height: 13px; }
    .toggle-item .toggle-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
    .toggle-item .toggle-count { font-size: 10px; color: #94a3b8; flex-shrink: 0; }

    /* ── Map ── */
    #map-container { flex: 1; position: relative; }
    #map { position: absolute; inset: 0; }

    .maplibregl-popup-content {
      font-size: 12px;
      padding: 8px 10px;
      border-radius: 6px;
      line-height: 1.5;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
      max-width: 240px;
    }
    .popup-name { font-weight: 600; margin-bottom: 3px; color: #0f172a; }
    .popup-col { color: #64748b; font-size: 11px; }
    .popup-val { color: #1e293b; font-weight: 500; }
    .popup-desc { color: #94a3b8; font-size: 10px; margin-top: 3px; font-style: italic; }
  </style>
</head>
<body>

<div id="header">
  <div>
    <h1>GeoQuery — Results Map</h1>
    <div class="subtitle" id="header-subtitle"></div>
  </div>
  <div class="badge" id="header-badge"></div>
</div>

<div id="app">
  <div id="sidebar">

    <div class="panel">
      <div class="panel-title">Column</div>
      <select id="col-select" onchange="onColumnChange()"></select>
    </div>

    <div class="panel">
      <div class="panel-title">Color Scheme</div>
      <select id="palette-select" onchange="onPaletteChange()"></select>
    </div>

    <div class="panel">
      <div class="panel-title">Classification</div>
      <select id="method-select" onchange="onMethodChange()">
        <option value="quantile">Quantile</option>
        <option value="equal">Equal Interval</option>
        <option value="jenks">Natural Breaks (Jenks)</option>
      </select>
    </div>

    <div class="panel">
      <div class="panel-title">Legend</div>
      <div id="legend-items"><div style="font-size:11px;color:#94a3b8">Loading…</div></div>
    </div>

    <div class="panel">
      <div class="panel-title">Statistics</div>
      <div class="stats-grid">
        <div class="stat-item"><div class="stat-label">Min</div><div class="stat-value" id="stat-min">—</div></div>
        <div class="stat-item"><div class="stat-label">Max</div><div class="stat-value" id="stat-max">—</div></div>
        <div class="stat-item"><div class="stat-label">Mean</div><div class="stat-value" id="stat-mean">—</div></div>
        <div class="stat-item"><div class="stat-label">Features</div><div class="stat-value" id="stat-n">—</div></div>
      </div>
    </div>

    <div class="panel" id="fc-panel">
      <div class="panel-title">Feature Collections</div>
      <div id="fc-toggles"></div>
    </div>

  </div>

  <div id="map-container">
    <div id="map"></div>
  </div>
</div>

<script>
  const DATA = __GQ_DATA__;

  // ── Color palettes (5-class ColorBrewer) ───────────────────────────────────
  const PALETTES = {
    'YlOrRd':  { label: 'Yellow → Orange → Red',  colors: ['#ffffb2','#fecc5c','#fd8d3c','#f03b20','#bd0026'] },
    'Blues':   { label: 'Blues',                   colors: ['#eff3ff','#bdd7e7','#6baed6','#3182bd','#08519c'] },
    'Greens':  { label: 'Greens',                  colors: ['#edf8e9','#bae4b3','#74c476','#31a354','#006d2c'] },
    'Purples': { label: 'Purples',                 colors: ['#f2f0f7','#cbc9e2','#9e9ac8','#756bb1','#54278f'] },
    'Oranges': { label: 'Oranges',                 colors: ['#feedde','#fdbe85','#fd8d3c','#e6550d','#a63603'] },
    'YlGn':    { label: 'Yellow → Green',          colors: ['#ffffcc','#c2e699','#78c679','#31a354','#006837'] },
    'RdYlGn':  { label: 'Red → Yellow → Green ↔', colors: ['#d7191c','#fdae61','#ffffbf','#a6d96a','#1a9641'] },
    'RdBu':    { label: 'Red → Blue ↔',           colors: ['#ca0020','#f4a582','#f7f7f7','#92c5de','#0571b0'] },
    'PuOr':    { label: 'Purple → Orange ↔',      colors: ['#5e3696','#b2abd2','#f7f7f7','#fdb863','#e66101'] },
    'BrBG':    { label: 'Brown → Blue-Green ↔',   colors: ['#8c510a','#d8b365','#f5f5f5','#5ab4ac','#01665e'] },
  };

  // ── Visibility state ───────────────────────────────────────────────────────
  const hiddenFCs = new Set();

  function onFCToggle(el) {
    const fc = el.dataset.fc;
    if (el.checked) hiddenFCs.delete(fc); else hiddenFCs.add(fc);
    const vis = el.checked ? 'visible' : 'none';
    map.setLayoutProperty('fc-fill-' + fc, 'visibility', vis);
    map.setLayoutProperty('fc-line-' + fc, 'visibility', vis);
    applyColors();
  }

  // ── Visualization state ────────────────────────────────────────────────────
  let map;
  let currentColumn  = DATA.columns[0] || null;
  let currentPalette = 'YlOrRd';
  let currentMethod  = 'quantile';

  // ── Populate controls ──────────────────────────────────────────────────────
  document.getElementById('header-subtitle').textContent =
    DATA.selection_label || DATA.request_name || '';
  document.getElementById('header-badge').textContent =
    'Request ' + DATA.request_id.slice(0, 8) + '…';

  (function buildColumnSelect() {
    const sel = document.getElementById('col-select');
    for (const [group, cols] of Object.entries(DATA.col_groups)) {
      const og = document.createElement('optgroup');
      og.label = group;
      for (const col of cols) {
        const opt = document.createElement('option');
        opt.value = col;
        const parts = col.split('.');
        opt.textContent = parts.length > 1 ? parts.slice(1).join('.') : col;
        if (col === currentColumn) opt.selected = true;
        og.appendChild(opt);
      }
      sel.appendChild(og);
    }
  })();

  (function buildPaletteSelect() {
    const sel = document.getElementById('palette-select');
    for (const [key, p] of Object.entries(PALETTES)) {
      const opt = document.createElement('option');
      opt.value = key;
      opt.textContent = p.label;
      if (key === currentPalette) opt.selected = true;
      sel.appendChild(opt);
    }
  })();

  function buildFCToggles() {
    const fcCounts = {};
    for (const feat of Object.values(DATA.features)) {
      fcCounts[feat.fc] = (fcCounts[feat.fc] || 0) + 1;
    }
    const container = document.getElementById('fc-toggles');
    for (const fc of DATA.fc_names) {
      const label = document.createElement('label');
      label.className = 'toggle-item';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = true;
      cb.dataset.fc = fc;
      cb.onchange = function() { onFCToggle(this); };
      const name = document.createElement('span');
      name.className = 'toggle-label';
      name.textContent = fc;
      name.title = fc;
      const count = document.createElement('span');
      count.className = 'toggle-count';
      count.textContent = (fcCounts[fc] || 0) + ' features';
      label.append(cb, name, count);
      container.appendChild(label);
    }
  }

  // ── Map init ───────────────────────────────────────────────────────────────
  function initMap() {
    const { layers, namedFlavor } = basemaps;

    map = new maplibregl.Map({
      container: 'map',
      style: {
        version: 8,
        glyphs: 'https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf',
        sprite: 'https://protomaps.github.io/basemaps-assets/sprites/v4/light',
        sources: {
          protomaps: {
            type: 'vector',
            tiles: ['https://api.protomaps.com/tiles/v4/{z}/{x}/{y}.mvt?key=' + DATA.protomaps_api_key],
            maxzoom: 15,
            attribution: '<a href="https://protomaps.com">Protomaps</a> &copy; <a href="https://openstreetmap.org">OpenStreetMap</a>'
          }
        },
        layers: layers('protomaps', namedFlavor('light'), { lang: 'en' })
      },
      center: [0, 20],
      zoom: 2
    });

    map.on('load', () => {
      addFeatureLayers();
      setupHover();
      buildFCToggles();
      if (DATA.bbox) {
        map.fitBounds(
          [[DATA.bbox[0], DATA.bbox[1]], [DATA.bbox[2], DATA.bbox[3]]],
          { padding: 40, maxZoom: 10, duration: 0 }
        );
      }
      map.once('idle', applyColors);
    });
  }

  function addFeatureLayers() {
    for (const fc of DATA.fc_names) {
      map.addSource('fc-' + fc, {
        type: 'vector',
        tiles: [DATA.tile_base_url + '/api/features/tiles/' + fc + '/{z}/{x}/{y}.mvt'],
        minzoom: 0,
        maxzoom: 12,
        promoteId: { [fc]: 'id' }
      });

      map.addLayer({
        id: 'fc-fill-' + fc,
        type: 'fill',
        source: 'fc-' + fc,
        'source-layer': fc,
        paint: {
          'fill-color': ['case',
            ['boolean', ['feature-state', 'hover'], false], '#fff',
            '#cbd5e1'
          ],
          'fill-opacity': ['case',
            ['boolean', ['feature-state', 'hover'], false], 0.88,
            0.72
          ]
        }
      });

      map.addLayer({
        id: 'fc-line-' + fc,
        type: 'line',
        source: 'fc-' + fc,
        'source-layer': fc,
        paint: {
          'line-color': '#334155',
          'line-width': 0.75,
          'line-opacity': 1
        }
      });
    }
  }

  // ── Classification ─────────────────────────────────────────────────────────
  function quantileBreaks(values, n) {
    const sorted = [...values].sort((a, b) => a - b);
    if (sorted[0] === sorted[sorted.length - 1]) {
      return Array.from({ length: n + 1 }, () => sorted[0]);
    }
    const breaks = [sorted[0]];
    for (let i = 1; i <= n; i++) {
      breaks.push(sorted[Math.round((i / n) * (sorted.length - 1))]);
    }
    return breaks;
  }

  function equalBreaks(values, n) {
    const min = Math.min(...values), max = Math.max(...values);
    const step = (max - min) / n;
    return Array.from({ length: n + 1 }, (_, i) => min + i * step);
  }

  function getColor(value, breaks, palette) {
    if (value === null || value === undefined || isNaN(Number(value))) return '#cbd5e1';
    const v = Number(value);
    for (let i = 1; i < breaks.length; i++) {
      if (v <= breaks[i]) return palette[i - 1];
    }
    return palette[palette.length - 1];
  }

  // ── Apply choropleth colors ────────────────────────────────────────────────
  function buildColorExpression(fc, column, breaks, palette) {
    const expr = ['match', ['get', 'id']];
    for (const [idStr, feat] of Object.entries(DATA.features)) {
      if (feat.fc !== fc) continue;
      expr.push(parseInt(idStr), getColor(feat[column], breaks, palette));
    }
    expr.push('#cbd5e1');
    return expr;
  }

  function applyColors() {
    if (!currentColumn || !map) return;

    const palette = PALETTES[currentPalette].colors;
    const n = palette.length;

    const values = Object.values(DATA.features)
      .filter(f => !hiddenFCs.has(f.fc))
      .map(f => f[currentColumn])
      .filter(v => v !== null && v !== undefined && !isNaN(Number(v)))
      .map(Number);

    if (values.length === 0) {
      document.getElementById('legend-items').innerHTML =
        '<div style="font-size:11px;color:#94a3b8">No numeric data for this column.</div>';
      return;
    }

    let breaks;
    if (currentMethod === 'quantile') breaks = quantileBreaks(values, n);
    else if (currentMethod === 'equal') breaks = equalBreaks(values, n);
    else breaks = ss.jenks(values, n);

    for (const fc of DATA.fc_names) {
      map.setPaintProperty('fc-fill-' + fc, 'fill-color', [
        'case',
        ['boolean', ['feature-state', 'hover'], false], '#fff',
        buildColorExpression(fc, currentColumn, breaks, palette)
      ]);
    }

    renderLegend(breaks, palette);
    renderStats(values);
  }

  function fmt(v) {
    if (!isFinite(v)) return String(v);
    if (Math.abs(v) >= 10000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
    if (Math.abs(v) >= 100)   return v.toFixed(1);
    if (Math.abs(v) >= 1)     return v.toFixed(3);
    if (v === 0)               return '0';
    return v.toPrecision(3);
  }

  function renderLegend(breaks, palette) {
    const el = document.getElementById('legend-items');
    el.innerHTML = palette.map((color, i) =>
      '<div class="legend-item">' +
        '<span class="legend-swatch" style="background:' + color + '"></span>' +
        '<span>' + fmt(breaks[i]) + ' – ' + fmt(breaks[i + 1]) + '</span>' +
      '</div>'
    ).join('') +
      '<div class="legend-item" style="opacity:0.55">' +
        '<span class="legend-swatch" style="background:#cbd5e1"></span>' +
        '<span>No data</span>' +
      '</div>';
  }

  function renderStats(values) {
    const n = values.length;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const mean = values.reduce((a, b) => a + b, 0) / n;
    document.getElementById('stat-min').textContent  = fmt(min);
    document.getElementById('stat-max').textContent  = fmt(max);
    document.getElementById('stat-mean').textContent = fmt(mean);
    document.getElementById('stat-n').textContent    = n;
  }

  // ── Hover / popup ──────────────────────────────────────────────────────────
  function setupHover() {
    const popup = new maplibregl.Popup({
      closeButton: false, closeOnClick: false, maxWidth: '260px'
    });
    let hoveredId = null, hoveredFc = null;

    for (const fc of DATA.fc_names) {
      map.on('mousemove', 'fc-fill-' + fc, (e) => {
        if (!e.features.length) return;
        map.getCanvas().style.cursor = 'pointer';

        const f  = e.features[0];
        const id = f.id;
        const attrId = f.properties?.id ?? id;
        const feat = DATA.features[String(attrId)];

        if (hoveredId !== null) {
          map.setFeatureState(
            { source: 'fc-' + hoveredFc, sourceLayer: hoveredFc, id: hoveredId },
            { hover: false }
          );
        }
        hoveredId = id; hoveredFc = fc;
        map.setFeatureState({ source: 'fc-' + fc, sourceLayer: fc, id }, { hover: true });

        const name = feat ? feat.name : ('Feature ' + attrId);
        const val  = feat ? feat[currentColumn] : null;
        const colLabel = currentColumn && currentColumn.includes('.')
          ? currentColumn.split('.').slice(1).join('.')
          : (currentColumn || '');
        const valStr = (val !== null && val !== undefined) ? fmt(Number(val)) : '—';
        const colDesc = DATA.col_descriptions?.[currentColumn] || '';

        popup.setLngLat(e.lngLat).setHTML(
          '<div class="popup-name">' + name + '</div>' +
          '<span class="popup-col">' + colLabel + ': </span>' +
          '<span class="popup-val">' + valStr + '</span>' +
          (colDesc ? '<div class="popup-desc">' + colDesc + '</div>' : '')
        ).addTo(map);
      });

      map.on('mouseleave', 'fc-fill-' + fc, () => {
        map.getCanvas().style.cursor = '';
        if (hoveredId !== null) {
          map.setFeatureState(
            { source: 'fc-' + hoveredFc, sourceLayer: hoveredFc, id: hoveredId },
            { hover: false }
          );
          hoveredId = null; hoveredFc = null;
        }
        popup.remove();
      });
    }
  }

  // ── Control handlers ───────────────────────────────────────────────────────
  function onColumnChange()  { currentColumn  = document.getElementById('col-select').value;    applyColors(); }
  function onPaletteChange() { currentPalette = document.getElementById('palette-select').value; applyColors(); }
  function onMethodChange()  { currentMethod  = document.getElementById('method-select').value;  applyColors(); }

  initMap();
</script>
</body>
</html>
"""
