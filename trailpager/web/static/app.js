'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  routeId:         null,
  routeSource:     null,  // 'upload' | 'generated' | null
  startCoord:      null,  // [lat, lon]
  endCoord:        null,
  pickMode:        null,  // 'start' | 'end' | null
  previewDebounce: null,
  routeGenDebounce: null,
};

// ── Map ────────────────────────────────────────────────────────────────────
const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {
      osm: {
        type: 'raster',
        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
        tileSize: 256,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxzoom: 19,
      },
    },
    layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
  },
  center: [-79.0, 37.9],
  zoom: 9,
});

map.addControl(new maplibregl.NavigationControl(), 'bottom-right');
map.addControl(new maplibregl.ScaleControl({ unit: 'imperial' }), 'bottom-left');

map.on('load', () => {
  map.addSource('route', { type: 'geojson', data: emptyFC() });
  map.addLayer({
    id: 'route-line',
    type: 'line',
    source: 'route',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': '#c0392b', 'line-width': 3, 'line-opacity': 0.9 },
  });

  map.addSource('frames', { type: 'geojson', data: emptyFC() });
  map.addLayer({
    id: 'frames-fill',
    type: 'fill',
    source: 'frames',
    paint: { 'fill-color': '#2980b9', 'fill-opacity': 0.08 },
  });
  map.addLayer({
    id: 'frames-outline',
    type: 'line',
    source: 'frames',
    paint: { 'line-color': '#2980b9', 'line-width': 1.5, 'line-opacity': 0.7 },
  });
  map.addLayer({
    id: 'frames-labels',
    type: 'symbol',
    source: 'frames',
    layout: {
      'text-field': ['to-string', ['get', 'page']],
      'text-size': 12,
      'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold'],
      'text-anchor': 'center',
    },
    paint: { 'text-color': '#2980b9', 'text-halo-color': '#fff', 'text-halo-width': 1.5 },
  });
});

// ── Map click ──────────────────────────────────────────────────────────────
map.on('click', (e) => {
  if (!state.pickMode) return;
  const { lat, lng } = e.lngLat;
  setCoord(state.pickMode, [lat, lng]);
  cancelPickMode();
  onCoordsChanged();
});

// ── DOM refs ───────────────────────────────────────────────────────────────
const elDropZone        = document.getElementById('drop-zone');
const elFileInput       = document.getElementById('file-input');
const elRouteEmpty      = document.getElementById('route-empty');
const elRouteGenerating = document.getElementById('route-generating');
const elRouteLoaded     = document.getElementById('route-loaded');
const elRouteFilename   = document.getElementById('route-filename');
const elBtnClearRoute   = document.getElementById('btn-clear-route');
const elBtnSaveGpx      = document.getElementById('btn-save-gpx');
const elBtnSaveGeojson  = document.getElementById('btn-save-geojson');
const elUploadWarnings  = document.getElementById('upload-warnings');

const elInputStart      = document.getElementById('input-start');
const elInputEnd        = document.getElementById('input-end');
const elPreviewSpinner  = document.getElementById('preview-spinner');
const elPreviewInfo     = document.getElementById('preview-info');
const elPreviewPages    = document.getElementById('preview-pages');
const elPreviewMiles    = document.getElementById('preview-miles');
const elPreviewWarnings = document.getElementById('preview-warnings');

const elBtnPickStart    = document.querySelector('.btn-pick[data-target="start"]');
const elBtnPickEnd      = document.querySelector('.btn-pick[data-target="end"]');

const elSelScale        = document.getElementById('sel-scale');
const elSelPaper        = document.getElementById('sel-paper');
const elInpOverlap      = document.getElementById('inp-overlap');
const elInpUtmZone      = document.getElementById('inp-utm-zone');

const elBtnGenerate     = document.getElementById('btn-generate');
const elGenProgress     = document.getElementById('gen-progress');
const elGenStatus       = document.getElementById('gen-status');

const elPickBanner      = document.getElementById('pick-banner');
const elPickLabel       = document.getElementById('pick-label');
const elBtnCancelPick   = document.getElementById('btn-cancel-pick');

// ── Markers ────────────────────────────────────────────────────────────────
function makeMarkerEl(color) {
  const el = document.createElement('div');
  el.style.cssText = `width:14px;height:14px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.5);cursor:grab`;
  return el;
}
const startMarker = new maplibregl.Marker({ element: makeMarkerEl('#27ae60'), draggable: true });
const endMarker   = new maplibregl.Marker({ element: makeMarkerEl('#c0392b'), draggable: true });

startMarker.on('dragend', () => {
  const { lat, lng } = startMarker.getLngLat();
  setCoord('start', [lat, lng], false);
  onCoordsChanged();
});
endMarker.on('dragend', () => {
  const { lat, lng } = endMarker.getLngLat();
  setCoord('end', [lat, lng], false);
  onCoordsChanged();
});

// ── File upload ────────────────────────────────────────────────────────────
elDropZone.addEventListener('click',     () => elFileInput.click());
elDropZone.addEventListener('dragover',  (e) => { e.preventDefault(); elDropZone.classList.add('drag-over'); });
elDropZone.addEventListener('dragleave', () => elDropZone.classList.remove('drag-over'));
elDropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  elDropZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
});
elFileInput.addEventListener('change', () => {
  if (elFileInput.files[0]) handleFile(elFileInput.files[0]);
});
elBtnClearRoute.addEventListener('click', clearRoute);

async function handleFile(file) {
  setUploadWarnings([]);
  const fd = new FormData();
  fd.append('file', file);

  let data;
  try {
    const res = await fetch('/api/route', { method: 'POST', body: fd });
    data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Upload failed');
  } catch (err) {
    setUploadWarnings([err.message]);
    return;
  }

  applyRouteData(data, file.name, 'upload');
}

// ── Route from points (OSRM) ───────────────────────────────────────────────
function scheduleRouteGeneration() {
  clearTimeout(state.routeGenDebounce);
  state.routeGenDebounce = setTimeout(generateRouteFromPoints, 600);
}

async function generateRouteFromPoints() {
  if (!state.startCoord || !state.endCoord) return;

  setRouteState('generating');
  setUploadWarnings([]);

  let data;
  try {
    const res = await fetch('/api/route-from-points', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start: state.startCoord, end: state.endCoord }),
    });
    data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Routing failed');
  } catch (err) {
    setRouteState('empty');
    setUploadWarnings([err.message]);
    return;
  }

  applyRouteData(data, 'Generated route', 'generated');
}

// ── Shared post-load handler ───────────────────────────────────────────────
function applyRouteData(data, label, source) {
  state.routeId     = data.route_id;
  state.routeSource = source;

  elRouteFilename.textContent = label;
  setRouteState('loaded');

  map.getSource('route').setData(data.geojson);

  const [minx, miny, maxx, maxy] = data.bounds;
  map.fitBounds([[minx, miny], [maxx, maxy]], { padding: 60, duration: 500 });

  // For uploads: place markers at default endpoints
  // For generated: markers are already placed (we used them for routing)
  if (source === 'upload') {
    setCoord('start', data.default_start);
    setCoord('end',   data.default_end);
  }

  if (data.warnings?.length) setUploadWarnings(data.warnings);
  schedulePreview();
}

function clearRoute() {
  state.routeId     = null;
  state.routeSource = null;
  state.startCoord  = null;
  state.endCoord    = null;

  setRouteState('empty');
  elInputStart.value = '';
  elInputEnd.value   = '';
  map.getSource('route')?.setData(emptyFC());
  map.getSource('frames')?.setData(emptyFC());
  elPreviewInfo.classList.add('hidden');
  setUploadWarnings([]);
  setPreviewWarnings([]);
  startMarker.remove();
  endMarker.remove();
  elBtnGenerate.disabled = true;
  elFileInput.value = '';
}

function setRouteState(state_) {
  elRouteEmpty.classList.toggle('hidden',      state_ !== 'empty');
  elRouteGenerating.classList.toggle('hidden', state_ !== 'generating');
  elRouteLoaded.classList.toggle('hidden',     state_ !== 'loaded');
}

// ── Export ─────────────────────────────────────────────────────────────────
elBtnSaveGpx.addEventListener('click', () => triggerExport('gpx'));
elBtnSaveGeojson.addEventListener('click', () => triggerExport('geojson'));

function triggerExport(fmt) {
  if (!state.routeId) return;
  const a = document.createElement('a');
  a.href = `/api/export/${state.routeId}/${fmt}`;
  a.download = `route.${fmt}`;
  a.click();
}

// ── Coord / pick ───────────────────────────────────────────────────────────
function setCoord(which, latlon, updateInput = true) {
  if (which === 'start') {
    state.startCoord = latlon;
    if (updateInput) elInputStart.value = latlon.map(v => v.toFixed(5)).join(', ');
    startMarker.setLngLat([latlon[1], latlon[0]]).addTo(map);
  } else {
    state.endCoord = latlon;
    if (updateInput) elInputEnd.value = latlon.map(v => v.toFixed(5)).join(', ');
    endMarker.setLngLat([latlon[1], latlon[0]]).addTo(map);
  }
}

function parseCoordInput(str) {
  const parts = str.split(',').map(s => parseFloat(s.trim()));
  if (parts.length === 2 && parts.every(n => !isNaN(n))) return parts;
  return null;
}

elInputStart.addEventListener('change', () => {
  const c = parseCoordInput(elInputStart.value);
  if (c) { setCoord('start', c, false); onCoordsChanged(); }
});
elInputEnd.addEventListener('change', () => {
  const c = parseCoordInput(elInputEnd.value);
  if (c) { setCoord('end', c, false); onCoordsChanged(); }
});

elBtnPickStart.addEventListener('click', () => togglePickMode('start'));
elBtnPickEnd.addEventListener('click',   () => togglePickMode('end'));
elBtnCancelPick.addEventListener('click', cancelPickMode);

function togglePickMode(which) {
  if (state.pickMode === which) { cancelPickMode(); return; }
  state.pickMode = which;
  map.getCanvas().style.cursor = 'crosshair';
  elBtnPickStart.classList.toggle('active', which === 'start');
  elBtnPickEnd.classList.toggle('active',   which === 'end');
  elPickLabel.textContent = `Click on the map to set ${which} point`;
  elPickBanner.classList.remove('hidden');
}

function cancelPickMode() {
  state.pickMode = null;
  map.getCanvas().style.cursor = '';
  elBtnPickStart.classList.remove('active');
  elBtnPickEnd.classList.remove('active');
  elPickBanner.classList.add('hidden');
}

// ── Central coord-change dispatcher ───────────────────────────────────────
function onCoordsChanged() {
  if (!state.startCoord || !state.endCoord) return;

  if (state.routeSource === 'upload') {
    // Trim existing uploaded route to new start/end
    schedulePreview();
  } else {
    // No route yet, or previous route was generated — re-generate
    scheduleRouteGeneration();
  }
}

// ── Settings change ────────────────────────────────────────────────────────
[elSelScale, elSelPaper, elInpOverlap, elInpUtmZone].forEach(el => {
  el.addEventListener('change', () => {
    if (state.routeId) schedulePreview();
  });
});

// ── Preview (page frames) ──────────────────────────────────────────────────
function schedulePreview() {
  clearTimeout(state.previewDebounce);
  state.previewDebounce = setTimeout(runPreview, 400);
}

async function runPreview() {
  if (!state.routeId || !state.startCoord || !state.endCoord) return;

  elPreviewSpinner.classList.remove('hidden');
  elPreviewInfo.classList.add('hidden');

  let data;
  try {
    const res = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildRequestBody()),
    });
    data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Preview failed');
  } catch (err) {
    elPreviewSpinner.classList.add('hidden');
    setPreviewWarnings([err.message]);
    return;
  }

  elPreviewSpinner.classList.add('hidden');

  if (data.route_geojson) map.getSource('route').setData(data.route_geojson);
  map.getSource('frames').setData(data.frames);

  elPreviewPages.textContent = `${data.page_count} page${data.page_count !== 1 ? 's' : ''}`;
  elPreviewMiles.textContent = `${data.length_miles} mi`;
  elPreviewInfo.classList.remove('hidden');

  setPreviewWarnings(data.warnings?.length ? data.warnings : []);
  elBtnGenerate.disabled = false;
}

// ── Generate PDF ───────────────────────────────────────────────────────────
elBtnGenerate.addEventListener('click', async () => {
  if (!state.routeId) return;

  elBtnGenerate.disabled = true;
  elGenProgress.classList.remove('hidden');
  showStatus('Generating PDF — this may take a minute…', false);

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...buildRequestBody(), layers: buildLayers() }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Generation failed');
    }
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = 'trail_map.pdf'; a.click();
    URL.revokeObjectURL(url);
    showStatus('✓ PDF downloaded', false);
  } catch (err) {
    showStatus(err.message, true);
  } finally {
    elBtnGenerate.disabled = false;
    elGenProgress.classList.add('hidden');
  }
});

// ── Helpers ────────────────────────────────────────────────────────────────
function buildRequestBody() {
  const [size, orient] = elSelPaper.value.split('_');
  return {
    route_id:    state.routeId,
    start:       state.startCoord,
    end:         state.endCoord,
    scale:       parseInt(elSelScale.value, 10),
    page_size:   size,
    orientation: orient,
    overlap_m:   parseFloat(elInpOverlap.value) || 500,
    margin_m:    200,
    utm_zone:    parseInt(elInpUtmZone.value, 10) || 17,
  };
}

function buildLayers() {
  return {
    topo_basemap:      document.getElementById('lyr-topo').checked,
    usfs_boundary:     document.getElementById('lyr-usfs').checked,
    nps_boundary:      document.getElementById('lyr-nps').checked,
    mile_markers:      document.getElementById('lyr-miles').checked,
    utm_grid:          document.getElementById('lyr-grid').checked,
    elevation_profile: document.getElementById('lyr-elev').checked,
    pois:              document.getElementById('lyr-pois').checked,
  };
}

function emptyFC() {
  return { type: 'FeatureCollection', features: [] };
}

function setUploadWarnings(msgs) {
  elUploadWarnings.textContent = msgs.join('\n');
  elUploadWarnings.classList.toggle('hidden', !msgs.length);
}

function setPreviewWarnings(msgs) {
  elPreviewWarnings.textContent = msgs.join('\n');
  elPreviewWarnings.classList.toggle('hidden', !msgs.length);
}

function showStatus(msg, isError) {
  elGenStatus.textContent = msg;
  elGenStatus.className   = isError ? 'error' : '';
  elGenStatus.classList.remove('hidden');
}
