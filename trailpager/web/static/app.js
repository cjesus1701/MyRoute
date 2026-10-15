'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  // Shared
  routeId:     null,
  routeSource: null,   // 'upload' | 'drawn' | null

  // Upload mode
  startCoord: null,    // [lat, lon]
  endCoord:   null,
  pickMode:   null,    // 'start' | 'end' | null

  // Draw mode
  waypoints:        [],   // [[lat, lon], ...]
  segmentCoords:    [],   // [[[lon, lat], ...], ...]  one array per segment
  segmentDetoured:  [],   // bool[] — true when segment fell back to straight line
  redoStack:        [],   // [{wp:[lat,lon], seg:[[lon,lat],...] | null, det:bool}]
  isFetchingSegment: false,

  previewDebounce: null,
  commitDebounce:  null,
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
  // Route line (solid red for properly routed segments)
  map.addSource('route', { type: 'geojson', data: emptyFC() });
  map.addLayer({
    id: 'route-line', type: 'line', source: 'route',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': '#c0392b', 'line-width': 3, 'line-opacity': 0.9 },
  });

  // Detour overlay (dashed orange for straight-line fallback segments)
  map.addSource('route-detour', { type: 'geojson', data: emptyFC() });
  map.addLayer({
    id: 'route-detour-line', type: 'line', source: 'route-detour',
    layout: { 'line-join': 'round', 'line-cap': 'butt' },
    paint: { 'line-color': '#e67e22', 'line-width': 2.5, 'line-opacity': 0.95, 'line-dasharray': [5, 4] },
  });

  // Page frames
  map.addSource('frames', { type: 'geojson', data: emptyFC() });
  map.addLayer({ id: 'frames-fill', type: 'fill', source: 'frames', paint: { 'fill-color': '#2980b9', 'fill-opacity': 0.08 } });
  map.addLayer({ id: 'frames-outline', type: 'line', source: 'frames', paint: { 'line-color': '#2980b9', 'line-width': 1.5, 'line-opacity': 0.7 } });
  map.addLayer({
    id: 'frames-labels', type: 'symbol', source: 'frames',
    layout: { 'text-field': ['to-string', ['get', 'page']], 'text-size': 12, 'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold'], 'text-anchor': 'center' },
    paint: { 'text-color': '#2980b9', 'text-halo-color': '#fff', 'text-halo-width': 1.5 },
  });

  // Waypoint dots (draw mode)
  map.addSource('waypoints', { type: 'geojson', data: emptyFC() });
  // White halo behind each dot
  map.addLayer({ id: 'wp-halo', type: 'circle', source: 'waypoints', paint: { 'circle-radius': 8, 'circle-color': '#fff', 'circle-opacity': 0.9 } });
  // Coloured dot: green = first, red = last, blue = intermediate
  map.addLayer({
    id: 'wp-dot', type: 'circle', source: 'waypoints',
    paint: {
      'circle-radius': 6,
      'circle-color': [
        'case',
        ['boolean', ['get', 'isFirst'], false], '#27ae60',
        ['boolean', ['get', 'isLast'],  false], '#c0392b',
        '#3498db',
      ],
    },
  });
  // Index label inside each dot
  map.addLayer({
    id: 'wp-label', type: 'symbol', source: 'waypoints',
    layout: {
      'text-field': ['to-string', ['get', 'idx']],
      'text-size': 9,
      'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold'],
      'text-anchor': 'center',
      'text-allow-overlap': true,
    },
    paint: { 'text-color': '#fff' },
  });
});

// ── Map click dispatcher ───────────────────────────────────────────────────
map.on('click', (e) => {
  const { lat, lng } = e.lngLat;
  if (state.pickMode) {
    // Upload mode: set start or end
    setCoord(state.pickMode, [lat, lng]);
    cancelPickMode();
    onUploadCoordsChanged();
  } else if (state.routeSource !== 'upload') {
    // Draw mode: add a waypoint
    addWaypoint([lat, lng]);
  }
});

// Change cursor to crosshair while over the map in draw mode
map.on('mousemove', () => {
  if (!state.pickMode && state.routeSource !== 'upload' && !state.isFetchingSegment) {
    map.getCanvas().style.cursor = 'crosshair';
  }
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

const elEpUpload        = document.getElementById('ep-upload');
const elEpDraw          = document.getElementById('ep-draw');
const elDrawHint        = document.getElementById('draw-hint');
const elDrawStats       = document.getElementById('draw-stats');
const elDrawWpCount     = document.getElementById('draw-wp-count');
const elDrawFetching    = document.getElementById('draw-fetching');
const elBtnUndo         = document.getElementById('btn-undo');
const elBtnRedo         = document.getElementById('btn-redo');
const elModeHintRouted  = document.getElementById('draw-mode-hint');
const elModeHintFree    = document.getElementById('draw-mode-hint-free');

// Mode toggle
function getDrawMode() {
  return document.querySelector('input[name="draw-mode"]:checked')?.value ?? 'routed';
}
document.querySelectorAll('input[name="draw-mode"]').forEach(el => {
  el.addEventListener('change', () => {
    const isFree = getDrawMode() === 'freehand';
    elModeHintRouted.classList.toggle('hidden', isFree);
    elModeHintFree.classList.toggle('hidden', !isFree);
  });
});

const elInputStart      = document.getElementById('input-start');
const elInputEnd        = document.getElementById('input-end');
const elBtnPickStart    = document.querySelector('.btn-pick[data-target="start"]');
const elBtnPickEnd      = document.querySelector('.btn-pick[data-target="end"]');

const elPreviewSpinner  = document.getElementById('preview-spinner');
const elPreviewInfo     = document.getElementById('preview-info');
const elPreviewPages    = document.getElementById('preview-pages');
const elPreviewMiles    = document.getElementById('preview-miles');
const elPreviewWarnings = document.getElementById('preview-warnings');

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

// ── Upload-mode markers ────────────────────────────────────────────────────
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
  onUploadCoordsChanged();
});
endMarker.on('dragend', () => {
  const { lat, lng } = endMarker.getLngLat();
  setCoord('end', [lat, lng], false);
  onUploadCoordsChanged();
});

// ── File upload ────────────────────────────────────────────────────────────
elDropZone.addEventListener('click',     () => elFileInput.click());
elDropZone.addEventListener('dragover',  (e) => { e.preventDefault(); elDropZone.classList.add('drag-over'); });
elDropZone.addEventListener('dragleave', () => elDropZone.classList.remove('drag-over'));
elDropZone.addEventListener('drop', (e) => {
  e.preventDefault(); elDropZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
});
elFileInput.addEventListener('change', () => { if (elFileInput.files[0]) handleFile(elFileInput.files[0]); });

async function handleFile(file) {
  setUploadWarnings([]);
  const fd = new FormData();
  fd.append('file', file);
  let data;
  try {
    const res = await fetch('/api/route', { method: 'POST', body: fd });
    data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Upload failed');
  } catch (err) { setUploadWarnings([err.message]); return; }

  clearDrawing();
  applyRouteData(data, file.name, 'upload');
  setEndpointsMode('upload');
}

// ── Draw mode: multi-waypoint ──────────────────────────────────────────────
async function addWaypoint(latlon) {
  if (state.isFetchingSegment) return;

  const isFirst    = state.waypoints.length === 0;
  const prevWaypoint = isFirst ? null : state.waypoints[state.waypoints.length - 1];

  state.waypoints.push(latlon);
  state.redoStack = [];        // new action clears redo history
  updateDrawDisplay();

  if (!isFirst) {
    if (getDrawMode() === 'freehand') {
      // Straight line between the two clicks — no routing API needed
      const segCoords = [
        [prevWaypoint[1], prevWaypoint[0]],
        [latlon[1],       latlon[0]],
      ];
      state.segmentCoords.push(segCoords);
      state.segmentDetoured.push(false);
      updateRouteLineFromSegments();
      updateDrawDisplay();
      scheduleCommit();
    } else {
      state.isFetchingSegment = true;
      map.getCanvas().style.cursor = 'progress';
      elDrawFetching.classList.remove('hidden');

      let segCoords, detoured = false;
      try {
        const res = await fetch('/api/route-segment', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ start: prevWaypoint, end: latlon }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Routing failed');
        segCoords = data.coordinates;
        detoured  = data.detoured || false;
      } catch (err) {
        // Revert the waypoint we optimistically added
        state.waypoints.pop();
        state.redoStack = [];
        updateDrawDisplay();
        setUploadWarnings([err.message]);
        return;
      } finally {
        state.isFetchingSegment = false;
        map.getCanvas().style.cursor = 'crosshair';
        elDrawFetching.classList.add('hidden');
      }

      state.segmentCoords.push(segCoords);
      state.segmentDetoured.push(detoured);
      if (detoured) showDetourToast();
      updateRouteLineFromSegments();
      updateDrawDisplay();
      scheduleCommit();
    }
  }
}

function undoWaypoint() {
  if (state.waypoints.length === 0 || state.isFetchingSegment) return;

  const wp  = state.waypoints.pop();
  const seg = state.segmentCoords.length > 0 ? state.segmentCoords.pop() : null;
  const det = state.segmentDetoured.length > 0 ? state.segmentDetoured.pop() : false;
  state.redoStack.push({ wp, seg, det });

  updateDrawDisplay();
  updateRouteLineFromSegments();
  map.getSource('frames').setData(emptyFC());

  if (state.segmentCoords.length > 0) {
    scheduleCommit();
  } else {
    // No segments left — drop the route_id so Generate PDF disables
    state.routeId     = null;
    state.routeSource = null;
    setRouteState('empty');
    elPreviewInfo.classList.add('hidden');
    setPreviewWarnings([]);
    elBtnGenerate.disabled = true;
  }
}

function redoWaypoint() {
  if (state.redoStack.length === 0 || state.isFetchingSegment) return;

  const { wp, seg, det } = state.redoStack.pop();
  state.waypoints.push(wp);
  if (seg) { state.segmentCoords.push(seg); state.segmentDetoured.push(det ?? false); }

  updateDrawDisplay();
  updateRouteLineFromSegments();

  if (state.segmentCoords.length > 0) scheduleCommit();
}

// ── Draw display helpers ───────────────────────────────────────────────────
function updateDrawDisplay() {
  // Waypoint dots on map
  const n = state.waypoints.length;
  const features = state.waypoints.map((wp, i) => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [wp[1], wp[0]] },
    properties: { isFirst: i === 0, isLast: i === n - 1 && n > 1, idx: i + 1 },
  }));
  map.getSource('waypoints').setData({ type: 'FeatureCollection', features });

  // Sidebar stats
  if (n > 0) {
    const s = state.segmentCoords.length;
    const d = state.segmentDetoured.filter(Boolean).length;
    const detourNote = d > 0 ? ` · ${d} straight-line` : '';
    elDrawWpCount.textContent = `${n} waypoint${n !== 1 ? 's' : ''} · ${s} segment${s !== 1 ? 's' : ''}${detourNote}`;
    elDrawStats.classList.remove('hidden');
    elDrawHint.classList.add('hidden');
  } else {
    elDrawStats.classList.add('hidden');
    elDrawHint.classList.remove('hidden');
  }

  elBtnUndo.disabled = n === 0 || state.isFetchingSegment;
  elBtnRedo.disabled = state.redoStack.length === 0 || state.isFetchingSegment;
}

function updateRouteLineFromSegments() {
  const coords = getCombinedCoords();
  if (coords.length >= 2) {
    map.getSource('route').setData({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: coords },
      properties: {},
    });
  } else {
    map.getSource('route').setData(emptyFC());
  }

  // Detour overlay: one feature per straight-line fallback segment
  const detourFeatures = state.segmentCoords
    .filter((_, i) => state.segmentDetoured[i])
    .map(seg => ({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: seg },
      properties: {},
    }));
  map.getSource('route-detour')?.setData({ type: 'FeatureCollection', features: detourFeatures });
}

function getCombinedCoords() {
  if (state.segmentCoords.length === 0) return [];
  const out = [...state.segmentCoords[0]];
  for (let i = 1; i < state.segmentCoords.length; i++) {
    out.push(...state.segmentCoords[i].slice(1));
  }
  return out;
}

// ── Commit accumulated route to backend ───────────────────────────────────
function scheduleCommit() {
  clearTimeout(state.commitDebounce);
  state.commitDebounce = setTimeout(commitRoute, 600);
}

async function commitRoute() {
  const coords = getCombinedCoords();
  if (coords.length < 2) return;

  try {
    const res = await fetch('/api/route-commit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ coordinates: coords }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);

    state.routeId     = data.route_id;
    state.routeSource = 'drawn';

    elRouteFilename.textContent = `Drawn route · ${state.waypoints.length} waypoint${state.waypoints.length !== 1 ? 's' : ''}`;
    setRouteState('loaded');
    runPreview();           // preview immediately after commit (no extra debounce)
  } catch (err) {
    setPreviewWarnings([`Failed to save route: ${err.message}`]);
  }
}

// ── Undo / redo buttons + keyboard ────────────────────────────────────────
elBtnUndo.addEventListener('click', undoWaypoint);
elBtnRedo.addEventListener('click', redoWaypoint);

document.addEventListener('keydown', (e) => {
  const mod = e.ctrlKey || e.metaKey;
  if (!mod) return;
  if (e.key === 'z' && !e.shiftKey) { e.preventDefault(); undoWaypoint(); }
  if (e.key === 'y' || (e.key === 'z' && e.shiftKey)) { e.preventDefault(); redoWaypoint(); }
});

// ── Upload mode: coord inputs / pick ──────────────────────────────────────
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
  return (parts.length === 2 && parts.every(n => !isNaN(n))) ? parts : null;
}

elInputStart.addEventListener('change', () => {
  const c = parseCoordInput(elInputStart.value);
  if (c) { setCoord('start', c, false); onUploadCoordsChanged(); }
});
elInputEnd.addEventListener('change', () => {
  const c = parseCoordInput(elInputEnd.value);
  if (c) { setCoord('end', c, false); onUploadCoordsChanged(); }
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

function onUploadCoordsChanged() {
  if (state.startCoord && state.endCoord) schedulePreview();
}

// ── Settings changes ───────────────────────────────────────────────────────
[elSelScale, elSelPaper, elInpOverlap, elInpUtmZone].forEach(el => {
  el.addEventListener('change', () => { if (state.routeId) schedulePreview(); });
});
document.getElementById('lyr-bw').addEventListener('change', () => { if (state.routeId) schedulePreview(); });

// ── Preview (page frames) ──────────────────────────────────────────────────
function schedulePreview() {
  clearTimeout(state.previewDebounce);
  state.previewDebounce = setTimeout(runPreview, 400);
}

async function runPreview() {
  if (!state.routeId) return;

  // Determine start/end for the preview request
  let start, end;
  if (state.routeSource === 'upload') {
    if (!state.startCoord || !state.endCoord) return;
    start = state.startCoord;
    end   = state.endCoord;
  } else {
    // Drawn route: use first and last waypoints
    if (state.waypoints.length < 2) return;
    start = state.waypoints[0];
    end   = state.waypoints[state.waypoints.length - 1];
  }

  elPreviewSpinner.classList.remove('hidden');
  elPreviewInfo.classList.add('hidden');

  let data;
  try {
    const res = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...buildSettingsBody(), route_id: state.routeId, start, end }),
    });
    data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Preview failed');
  } catch (err) {
    elPreviewSpinner.classList.add('hidden');
    setPreviewWarnings([err.message]);
    return;
  }

  elPreviewSpinner.classList.add('hidden');

  // For uploaded routes, update the trimmed line; for drawn routes keep the accumulated line
  if (state.routeSource === 'upload' && data.route_geojson) {
    map.getSource('route').setData(data.route_geojson);
  }
  map.getSource('frames').setData(data.frames);

  elPreviewPages.textContent = `${data.page_count} page${data.page_count !== 1 ? 's' : ''}`;
  elPreviewMiles.textContent = `${data.length_miles} mi`;
  elPreviewInfo.classList.remove('hidden');
  setPreviewWarnings(data.warnings?.length ? data.warnings : []);
  elBtnGenerate.disabled = false;
}

// ── Export ─────────────────────────────────────────────────────────────────
elBtnSaveGpx.addEventListener('click',     () => triggerExport('gpx'));
elBtnSaveGeojson.addEventListener('click', () => triggerExport('geojson'));

function triggerExport(fmt) {
  if (!state.routeId) return;
  const a = document.createElement('a');
  a.href = `/api/export/${state.routeId}/${fmt}`;
  a.download = `route.${fmt}`;
  a.click();
}

// ── Generate PDF ───────────────────────────────────────────────────────────
elBtnGenerate.addEventListener('click', async () => {
  if (!state.routeId) return;

  let start, end;
  if (state.routeSource === 'upload') {
    start = state.startCoord; end = state.endCoord;
  } else {
    start = state.waypoints[0]; end = state.waypoints[state.waypoints.length - 1];
  }

  elBtnGenerate.disabled = true;
  elGenProgress.classList.remove('hidden');
  showStatus('Generating PDF — this may take a minute…', false);

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...buildSettingsBody(), route_id: state.routeId, start, end, layers: buildLayers() }),
    });
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Generation failed'); }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'trail_map.pdf'; a.click();
    URL.revokeObjectURL(url);
    showStatus('✓ PDF downloaded', false);
  } catch (err) {
    showStatus(err.message, true);
  } finally {
    elBtnGenerate.disabled = false;
    elGenProgress.classList.add('hidden');
  }
});

// ── Route lifecycle ────────────────────────────────────────────────────────
function applyRouteData(data, label, source) {
  state.routeId     = data.route_id;
  state.routeSource = source;

  elRouteFilename.textContent = label;
  setRouteState('loaded');

  map.getSource('route').setData(data.geojson);
  const [minx, miny, maxx, maxy] = data.bounds;
  map.fitBounds([[minx, miny], [maxx, maxy]], { padding: 60, duration: 500 });

  if (source === 'upload') {
    setCoord('start', data.default_start);
    setCoord('end',   data.default_end);
  }

  if (data.warnings?.length) setUploadWarnings(data.warnings);
  schedulePreview();
}

function clearDrawing() {
  state.waypoints        = [];
  state.segmentCoords    = [];
  state.segmentDetoured  = [];
  state.redoStack        = [];
  state.isFetchingSegment = false;
  clearTimeout(state.commitDebounce);
  map.getSource('waypoints')?.setData(emptyFC());
  map.getSource('route')?.setData(emptyFC());
  map.getSource('route-detour')?.setData(emptyFC());
  updateDrawDisplay();
}

elBtnClearRoute.addEventListener('click', clearRoute);
document.getElementById('btn-reverse-route').addEventListener('click', reverseRoute);

function reverseRoute() {
  if (!state.routeId) return;

  if (state.routeSource === 'upload') {
    [state.startCoord, state.endCoord] = [state.endCoord, state.startCoord];
    if (state.startCoord) setCoord('start', state.startCoord);
    if (state.endCoord)   setCoord('end',   state.endCoord);
    onUploadCoordsChanged();
  } else {
    // Reverse waypoints and segments in-place
    state.waypoints.reverse();
    state.segmentCoords.reverse();
    state.segmentCoords.forEach(seg => seg.reverse());
    state.segmentDetoured.reverse();
    state.redoStack = [];

    updateRouteLineFromSegments();
    updateDrawDisplay();
    scheduleCommit();
  }
}

function clearRoute() {
  state.routeId     = null;
  state.routeSource = null;
  state.startCoord  = null;
  state.endCoord    = null;

  clearDrawing();
  cancelPickMode();
  startMarker.remove();
  endMarker.remove();
  elInputStart.value = '';
  elInputEnd.value   = '';
  elFileInput.value  = '';

  setRouteState('empty');
  setEndpointsMode('draw');
  map.getSource('frames')?.setData(emptyFC());
  elPreviewInfo.classList.add('hidden');
  setUploadWarnings([]);
  setPreviewWarnings([]);
  elBtnGenerate.disabled = true;
}

// ── UI state helpers ───────────────────────────────────────────────────────
function setRouteState(s) {
  elRouteEmpty.classList.toggle('hidden',      s !== 'empty');
  elRouteGenerating.classList.toggle('hidden', s !== 'generating');
  elRouteLoaded.classList.toggle('hidden',     s !== 'loaded');
}

function setEndpointsMode(mode) {
  elEpUpload.classList.toggle('hidden', mode !== 'upload');
  elEpDraw.classList.toggle('hidden',   mode !== 'draw');
  if (mode !== 'upload') cancelPickMode();
}

// ── Request builders ───────────────────────────────────────────────────────
function buildSettingsBody() {
  const [size, orient] = elSelPaper.value.split('_');
  return {
    scale:       parseInt(elSelScale.value, 10),
    page_size:   size,
    orientation: orient,
    overlap_m:   parseFloat(elInpOverlap.value) || 500,
    margin_m:    200,
    utm_zone:    parseInt(elInpUtmZone.value, 10) || 17,
    bw_print:    document.getElementById('lyr-bw').checked,
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

// ── Misc helpers ───────────────────────────────────────────────────────────
function emptyFC() { return { type: 'FeatureCollection', features: [] }; }

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

// ── Detour toast ───────────────────────────────────────────────────────────
let _detourToastTimer = null;
function showDetourToast() {
  let toast = document.getElementById('detour-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'detour-toast';
    toast.className = 'detour-toast';
    document.body.appendChild(toast);
  }
  toast.textContent = 'Trail routing unavailable here — segment shown as straight line (orange dashed). Add more waypoints or switch to Freehand.';
  toast.classList.add('visible');
  clearTimeout(_detourToastTimer);
  _detourToastTimer = setTimeout(() => toast.classList.remove('visible'), 6000);
}
