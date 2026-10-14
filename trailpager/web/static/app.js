'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  routeId:   null,
  startCoord: null,   // [lat, lon]
  endCoord:   null,
  pickMode:   null,   // 'start' | 'end' | null
  previewDebounce: null,
};

// ── Map init ───────────────────────────────────────────────────────────────
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
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
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
  // Route line source + layer
  map.addSource('route', { type: 'geojson', data: emptyFC() });
  map.addLayer({
    id: 'route-line',
    type: 'line',
    source: 'route',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': '#c0392b', 'line-width': 3, 'line-opacity': 0.9 },
  });

  // Page frames
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

// ── Map click handler ──────────────────────────────────────────────────────
map.on('click', (e) => {
  if (!state.pickMode) return;
  const { lat, lng } = e.lngLat;
  setCoord(state.pickMode, [lat, lng]);
  cancelPickMode();
  schedulePreview();
});

map.on('mouseenter', 'route-line', () => {
  if (state.pickMode) map.getCanvas().style.cursor = 'crosshair';
});
map.on('mouseleave', 'route-line', () => {
  if (!state.pickMode) map.getCanvas().style.cursor = '';
});

// ── DOM refs ───────────────────────────────────────────────────────────────
const elDropZone       = document.getElementById('drop-zone');
const elFileInput      = document.getElementById('file-input');
const elRouteInfo      = document.getElementById('route-info');
const elRouteFilename  = document.getElementById('route-filename');
const elBtnClearRoute  = document.getElementById('btn-clear-route');
const elUploadWarnings = document.getElementById('upload-warnings');

const elInputStart     = document.getElementById('input-start');
const elInputEnd       = document.getElementById('input-end');
const elPreviewSpinner = document.getElementById('preview-spinner');
const elPreviewInfo    = document.getElementById('preview-info');
const elPreviewPages   = document.getElementById('preview-pages');
const elPreviewMiles   = document.getElementById('preview-miles');
const elPreviewWarnings= document.getElementById('preview-warnings');

const elBtnPickStart   = document.querySelector('.btn-pick[data-target="start"]');
const elBtnPickEnd     = document.querySelector('.btn-pick[data-target="end"]');

const elSelScale       = document.getElementById('sel-scale');
const elSelPaper       = document.getElementById('sel-paper');
const elInpOverlap     = document.getElementById('inp-overlap');
const elInpUtmZone     = document.getElementById('inp-utm-zone');

const elBtnGenerate    = document.getElementById('btn-generate');
const elGenProgress    = document.getElementById('gen-progress');
const elGenStatus      = document.getElementById('gen-status');

const elPickBanner     = document.getElementById('pick-banner');
const elPickLabel      = document.getElementById('pick-label');
const elBtnCancelPick  = document.getElementById('btn-cancel-pick');

// ── Markers ────────────────────────────────────────────────────────────────
function makeMarker(color) {
  const el = document.createElement('div');
  el.style.cssText = `width:14px;height:14px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.5);cursor:grab`;
  return el;
}
const startMarker = new maplibregl.Marker({ element: makeMarker('#27ae60'), draggable: true });
const endMarker   = new maplibregl.Marker({ element: makeMarker('#c0392b'), draggable: true });

startMarker.on('dragend', () => {
  const { lat, lng } = startMarker.getLngLat();
  setCoord('start', [lat, lng], false);
  schedulePreview();
});
endMarker.on('dragend', () => {
  const { lat, lng } = endMarker.getLngLat();
  setCoord('end', [lat, lng], false);
  schedulePreview();
});

// ── File upload ────────────────────────────────────────────────────────────
elDropZone.addEventListener('click', () => elFileInput.click());
elDropZone.addEventListener('dragover', (e) => { e.preventDefault(); elDropZone.classList.add('drag-over'); });
elDropZone.addEventListener('dragleave', () => elDropZone.classList.remove('drag-over'));
elDropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  elDropZone.classList.remove('drag-over');
  const f = e.dataTransfer.files[0];
  if (f) handleFile(f);
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

  state.routeId = data.route_id;
  elRouteFilename.textContent = file.name;
  elDropZone.classList.add('hidden');
  elRouteInfo.classList.remove('hidden');

  // Draw route
  map.getSource('route').setData(data.geojson);

  // Fit bounds
  const [minx, miny, maxx, maxy] = data.bounds;
  map.fitBounds([[minx, miny], [maxx, maxy]], { padding: 60, duration: 600 });

  // Set default start / end
  setCoord('start', data.default_start);
  setCoord('end',   data.default_end);

  if (data.warnings?.length) setUploadWarnings(data.warnings);
  schedulePreview();
}

function clearRoute() {
  state.routeId   = null;
  state.startCoord = null;
  state.endCoord   = null;
  elDropZone.classList.remove('hidden');
  elRouteInfo.classList.add('hidden');
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

// ── Coord helpers ──────────────────────────────────────────────────────────
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
  if (c) { setCoord('start', c, false); schedulePreview(); }
});
elInputEnd.addEventListener('change', () => {
  const c = parseCoordInput(elInputEnd.value);
  if (c) { setCoord('end', c, false); schedulePreview(); }
});

// ── Pick mode ──────────────────────────────────────────────────────────────
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

// ── Settings change → re-preview ──────────────────────────────────────────
[elSelScale, elSelPaper, elInpOverlap, elInpUtmZone].forEach(el => {
  el.addEventListener('change', schedulePreview);
});

function schedulePreview() {
  clearTimeout(state.previewDebounce);
  state.previewDebounce = setTimeout(runPreview, 400);
}

// ── Preview ────────────────────────────────────────────────────────────────
async function runPreview() {
  if (!state.routeId || !state.startCoord || !state.endCoord) return;

  elPreviewSpinner.classList.remove('hidden');
  elPreviewInfo.classList.add('hidden');

  const body = buildRequestBody();
  let data;
  try {
    const res = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Preview failed');
  } catch (err) {
    elPreviewSpinner.classList.add('hidden');
    setPreviewWarnings([err.message]);
    return;
  }

  elPreviewSpinner.classList.add('hidden');

  // Update trimmed route line
  if (data.route_geojson) {
    map.getSource('route').setData(data.route_geojson);
  }

  // Update page frames
  map.getSource('frames').setData(data.frames);

  // Update info chips
  elPreviewPages.textContent = `${data.page_count} page${data.page_count !== 1 ? 's' : ''}`;
  elPreviewMiles.textContent = `${data.length_miles} mi`;
  elPreviewInfo.classList.remove('hidden');

  if (data.warnings?.length) setPreviewWarnings(data.warnings);
  else setPreviewWarnings([]);

  elBtnGenerate.disabled = false;
}

// ── Generate ───────────────────────────────────────────────────────────────
elBtnGenerate.addEventListener('click', async () => {
  if (!state.routeId) return;

  elBtnGenerate.disabled = true;
  elGenProgress.classList.remove('hidden');
  showStatus('Generating PDF — this may take a minute…', false);

  const body = { ...buildRequestBody(), layers: buildLayers() };

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Generation failed');
    }
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'trail_map.pdf';
    a.click();
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
  const paperVal  = elSelPaper.value;         // e.g. "letter_landscape"
  const [size, orient] = paperVal.split('_'); // ["letter","landscape"]
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
  if (!msgs.length) { elUploadWarnings.classList.add('hidden'); return; }
  elUploadWarnings.textContent = msgs.join('\n');
  elUploadWarnings.classList.remove('hidden');
}

function setPreviewWarnings(msgs) {
  if (!msgs.length) { elPreviewWarnings.classList.add('hidden'); return; }
  elPreviewWarnings.textContent = msgs.join('\n');
  elPreviewWarnings.classList.remove('hidden');
}

function showStatus(msg, isError) {
  elGenStatus.textContent = msg;
  elGenStatus.className   = isError ? 'error' : '';
  elGenStatus.classList.remove('hidden');
}
