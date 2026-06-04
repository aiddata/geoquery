TEMPLATE_CUSTOM = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>__GQ_TITLE__ — GeoQuery Results</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; display: flex; flex-direction: column; height: 100vh; }
  #header { background: #1e293b; color: #f8fafc; padding: 10px 16px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
  #header h1 { font-size: 15px; font-weight: 600; }
  #header .sub { font-size: 12px; color: #94a3b8; }
  #controls { background: #f8fafc; border-bottom: 1px solid #e2e8f0; padding: 8px 16px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; flex-shrink: 0; }
  #controls label { font-size: 12px; color: #475569; }
  #col-select { font-size: 12px; padding: 4px 8px; border: 1px solid #cbd5e1; border-radius: 4px; background: white; }
  #map { flex: 1; }
  .info-panel { background: white; padding: 10px 12px; border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,.2); font-size: 12px; min-width: 140px; }
  .info-panel h4 { margin-bottom: 6px; font-size: 13px; }
  .legend { line-height: 20px; }
  .legend i { width: 14px; height: 14px; display: inline-block; margin-right: 6px; border-radius: 2px; vertical-align: middle; }
  .no-data { color: #94a3b8; font-style: italic; }
</style>
</head>
<body>
<div id="header">
  <div>
    <h1>__GQ_TITLE__</h1>
    <div class="sub">Custom boundary · __GQ_FC__ · __GQ_FEAT_COUNT__ features</div>
  </div>
</div>
<div id="controls">
  <label for="col-select">Display column:</label>
  <select id="col-select"></select>
</div>
<div id="map"></div>

<script>
const DATA = __GQ_DATA__;
const GEOJSON_FILE = "__GQ_GEOJSON__";

const map = L.map("map");
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
  subdomains: "abcd", maxZoom: 19
}).addTo(map);

const info = L.control();
info.onAdd = function() {
  this._div = L.DomUtil.create("div", "info-panel");
  this.update();
  return this._div;
};
info.update = function(props) {
  if (!props) { this._div.innerHTML = "<h4>Hover a feature</h4>"; return; }
  const col = document.getElementById("col-select").value;
  const val = DATA.features[String(props.geom_id)]?.[col];
  this._div.innerHTML = "<h4>" + (props.name || "Feature " + props.geom_id) + "</h4>" +
    "<b>" + col + ":</b> " + (val == null ? "<span class=no-data>no data</span>" : val);
};
info.addTo(map);

const legend = L.control({ position: "bottomright" });

function getColor(val, breaks, colors) {
  if (val == null) return "#e2e8f0";
  for (let i = breaks.length - 1; i >= 0; i--) {
    if (val >= breaks[i]) return colors[i];
  }
  return colors[0];
}

const COLORS = ["#eff3ff","#bdd7e7","#6baed6","#3182bd","#08519c"];

let geojsonLayer = null;

function buildBreaks(vals) {
  const sorted = vals.filter(v => v != null).sort((a,b) => a-b);
  if (!sorted.length) return [];
  const n = COLORS.length;
  const breaks = [];
  for (let i = 0; i < n; i++) {
    breaks.push(sorted[Math.floor(i * sorted.length / n)] );
  }
  return [...new Set(breaks)];
}

function updateMap(col) {
  const vals = Object.values(DATA.features).map(f => {
    const v = f[col]; return (v == null || v === "") ? null : Number(v);
  });
  const isNumeric = vals.some(v => v != null && !isNaN(v));
  const breaks = isNumeric ? buildBreaks(vals.filter(v => v != null && !isNaN(v))) : [];

  if (geojsonLayer) geojsonLayer.remove();

  geojsonLayer = L.geoJSON(window._geoData, {
    style: function(feature) {
      const fdata = DATA.features[String(feature.properties.geom_id)];
      const val = fdata?.[col];
      const numVal = (val == null || val === "") ? null : Number(val);
      return {
        fillColor: isNumeric ? getColor(!isNaN(numVal) ? numVal : null, breaks, COLORS) : "#3182bd",
        weight: 1.5, color: "#1e40af", opacity: 1, fillOpacity: 0.6
      };
    },
    onEachFeature: function(feature, layer) {
      layer.on({
        mouseover: function(e) {
          e.target.setStyle({ weight: 2.5, fillOpacity: 0.8 });
          info.update(feature.properties);
        },
        mouseout: function(e) {
          geojsonLayer.resetStyle(e.target);
          info.update();
        }
      });
    }
  }).addTo(map);

  // Update legend
  legend.onAdd = function() {
    const div = L.DomUtil.create("div", "info-panel legend");
    if (!isNumeric || !breaks.length) {
      div.innerHTML = "<i style='background:#3182bd'></i> Value";
      return div;
    }
    div.innerHTML = "";
    for (let i = 0; i < breaks.length; i++) {
      div.innerHTML += "<i style='background:" + COLORS[i] + "'></i>" +
        (i < breaks.length - 1
          ? breaks[i].toFixed(2) + " &ndash; " + breaks[i+1].toFixed(2)
          : "&ge; " + breaks[i].toFixed(2)) + "<br>";
    }
    return div;
  };
  legend.addTo(map);
}

// Populate column selector
const colSelect = document.getElementById("col-select");
DATA.columns.forEach(col => {
  const opt = document.createElement("option");
  opt.value = col; opt.textContent = col;
  colSelect.appendChild(opt);
});
colSelect.addEventListener("change", () => updateMap(colSelect.value));

// Load GeoJSON file
fetch(GEOJSON_FILE)
  .then(r => r.json())
  .then(gj => {
    window._geoData = gj;
    if (DATA.bbox) {
      map.fitBounds([[DATA.bbox[1], DATA.bbox[0]], [DATA.bbox[3], DATA.bbox[2]]]);
    } else {
      map.setView([0, 20], 2);
    }
    if (DATA.columns.length) updateMap(DATA.columns[0]);
    else L.geoJSON(gj, { style: { color: "#1e40af", fillColor: "#3182bd", fillOpacity: 0.5, weight: 1.5 } }).addTo(map);
  })
  .catch(err => {
    document.getElementById("map").innerHTML =
      "<p style='padding:20px;color:#dc2626'>Failed to load boundary file: " + err + "</p>";
  });
</script>
</body>
</html>
"""
