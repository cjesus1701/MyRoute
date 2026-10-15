'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  routes:      [],    // {routeId,filename,color,geojson,bounds,startCoord,endCoord,elevationProfile,distanceMiles,gainFt,lossFt,warnings}[]
  selectedIdx: null,  // index of selected uploaded route, or null

  // Active route for PDF
  routeId:     null,
  routeSource: null,  // 'upload' | 'drawn' | null
  startCoord:  null,
  endCoord:    null,

  // Drawn route
  drawnRouteId:      null,
  waypoints:         [],
  segmentCoords:     [],
  segmentDetoured:   [],
  redoStack:         [],
  isFetchingSegment: false,

  pickMode:        null,
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
  // Drawn route line
  map.addSource('route', { type: 'geojson', data: emptyFC() });
  map.addLayer({
    id: 'route-line', type: 'line', source: 'route',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': '#c0392b', 'line-width': 3, 'line-opacity': 0.9 },
  });

  // Detour overlay (dashed orange)
  map.addSource('route-detour', { type: 'geojson', data: emptyFC() });
  map.addLayer({
    id: 'route-detour-line', type: 'line', source: 'route-detour',
    layout: { 'line-join': 'round', 'line-cap': 'butt' },
    paint: { 'line-color': '#e67e22', 'line-width': 2.5, 'line-opacity': 0.95, 'line-dasharray': [5, 4] },
  });

  // Page frames
  map.addSource('frames', { type: 'geojson', data: emptyFC() });
  map.addLayer({ id: 'frames-fill',    type: 'fill',   source: 'frames', paint: { 'fill-color': '#2980b9', 'fill-opacity': 0.08 } });
  map.addLayer({ id: 'frames-outline', type: 'line',   source: 'frames', paint: { 'line-color': '#2980b9', 'line-width': 1.5, 'line-opacity': 0.7 } });
  map.addLayer({
    id: 'frames-labels', type: 'symbol', source: 'frames',
    layout: { 'text-field': ['to-string', ['get', 'page']], 'text-size': 12, 'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold'], 'text-anchor': 'center' },
    paint: { 'text-color': '#2980b9', 'text-halo-color': '#fff', 'text-halo-width': 1.5 },
  });

  // Waypoint dots
  map.addSource('waypoints', { type: 'geojson', data: emptyFC() });
  map.addLayer({ id: 'wp-halo', type: 'circle', source: 'waypoints', paint: { 'circle-radius': 8, 'circle-color': '#fff', 'circle-opacity': 0.9 } });
  map.addLayer({
    id: 'wp-dot', type: 'circle', source: 'waypoints',
    paint: {
      'circle-radius': 6,
      'circle-color': ['case',
        ['boolean', ['get', 'isFirst'], false], '#27ae60',
        ['boolean', ['get', 'isLast'],  false], '#c0392b',
        '#3498db'],
    },
  });
  map.addLayer({
    id: 'wp-label', type: 'symbol', source: 'waypoints',
    layout: { 'text-field': ['to-string', ['get', 'idx']], 'text-size': 9, 'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold'], 'text-anchor': 'center', 'text-allow-overlap': true },
    paint: { 'text-color': '#fff' },
  });
});

// ── Map click dispatcher ───────────────────────────────────────────────────
map.on('click', (e) => {
  const { lat, lng } = e.lngLat;
  if (state.pickMode) {
    setCoord(state.pickMode, [lat, lng]);
    cancelPickMode();
    onUploadCoordsChanged();
  } else if (state.selectedIdx === null) {
    addWaypoint([lat, lng]);
  }
});

map.on('mousemove', () => {
  if (!state.pickMode && state.selectedIdx === null && !state.isFetchingSegment) {
    map.getCanvas().style.cursor = 'crosshair';
  } else if (!state.pickMode) {
    map.getCanvas().style.cursor = '';
  }
});

// ── DOM refs ───────────────────────────────────────────────────────────────
const elDropZone           = document.getElementById('drop-zone');
const elFileInput          = document.getElementById('file-input');
const elRouteList          = document.getElementById('route-list');
const elRouteCountBadge    = document.getElementById('route-count-badge');
const elRouteGenerating    = document.getElementById('route-generating');
const elUploadWarnings     = document.getElementById('upload-warnings');
const elSelectedRouteLabel = document.getElementById('selected-route-label');

const elEpUpload           = document.getElementById('ep-upload');
const elEpDraw             = document.getElementById('ep-draw');
const elDrawHint           = document.getElementById('draw-hint');
const elDrawStats          = document.getElementById('draw-stats');
const elDrawWpCount        = document.getElementById('draw-wp-count');
const elDrawFetching       = document.getElementById('draw-fetching');
const elBtnUndo            = document.getElementById('btn-undo');
const elBtnRedo            = document.getElementById('btn-redo');
const elModeHintRouted     = document.getElementById('draw-mode-hint');
const elModeHintFree       = document.getElementById('draw-mode-hint-free');

const elInputStart         = document.getElementById('input-start');
const elInputEnd           = document.getElementById('input-end');
const elBtnPickStart       = document.querySelector('.btn-pick[data-target="start"]');
const elBtnPickEnd         = document.querySelector('.btn-pick[data-target="end"]');

const elPreviewSpinner     = document.getElementById('preview-spinner');
const elPreviewInfo        = document.getElementById('preview-info');
const elPreviewPages       = document.getElementById('preview-pages');
const elPreviewMiles       = document.getElementById('preview-miles');
const elPreviewWarnings    = document.getElementById('preview-warnings');

const elSelScale           = document.getElementById('sel-scale');
const elSelPaper           = document.getElementById('sel-paper');
const elInpOverlap         = document.getElementById('inp-overlap');
const elInpUtmZone         = document.getElementById('inp-utm-zone');

const elBtnGenerate        = document.getElementById('btn-generate');
const elGenProgress        = document.getElementById('gen-progress');
const elGenStatus          = document.getElementById('gen-status');
const elPickBanner         = document.getElementById('pick-banner');
const elPickLabel          = document.getElementById('pick-label');
const elBtnCancelPick      = document.getElementById('btn-cancel-pick');

const elElevPanel          = document.getElementById('elev-panel');
const elElevName           = document.getElementById('elev-name');
const elElevStats          = document.getElementById('elev-stats');
const elElevCanvas         = document.getElementById('elev-canvas');
const elElevClose          = document.getElementById('elev-close');

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
  e.preventDefault();
  elDropZone.classList.remove('drag-over');
  Array.from(e.dataTransfer.files).forEach(f => addRoute(f));
});
elFileInput.addEventListener('change', () => {
  Array.from(elFileInput.files).forEach(f => addRoute(f));
  elFileInput.value = '';
});

async function addRoute(file) {
  if (state.routes.length >= 5) {
    setUploadWarnings(['Maximum 5 routes — remove one first.']);
    return;
  }
  setUploadWarnings([]);
  elRouteGenerating.classList.remove('hidden');

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
  } finally {
    elRouteGenerating.classList.add('hidden');
  }

  // Clear drawn route when first upload arrives
  if (state.routes.length === 0 && state.waypoints.length > 0) {
    clearDrawing();
    state.drawnRouteId = null;
  }

  const route = {
    routeId:          data.route_id,
    filename:         file.name,
    color:            data.color,
    geojson:          data.geojson,
    bounds:           data.bounds,
    startCoord:       data.default_start,
    endCoord:         data.default_end,
    elevationProfile: data.elevation_profile || [],
    distanceMiles:    data.total_distance_miles || 0,
    gainFt:           data.gain_ft || 0,
    lossFt:           data.loss_ft || 0,
    warnings:         data.warnings || [],
  };

  state.routes.push(route);
  addRouteLayer(route);
  renderRouteList();

  // Auto-select first uploaded route
  if (state.routes.length === 1) selectRoute(0);
}

function addRouteLayer(route) {
  if (!map.isStyleLoaded()) { map.once('load', () => addRouteLayer(route)); return; }
  const srcId = `route-upload-${route.routeId}`;
  if (map.getSource(srcId)) return;
  map.addSource(srcId, { type: 'geojson', data: route.geojson });
  map.addLayer({
    id: `${srcId}-line`, type: 'line', source: srcId,
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': route.color, 'line-width': 3, 'line-opacity': 0.85 },
  });
}

// ── Multi-route management ─────────────────────────────────────────────────
function selectRoute(idx) {
  // Dehighlight previously selected
  if (state.selectedIdx !== null) {
    const prev = state.routes[state.selectedIdx];
    if (prev) {
      map.setPaintProperty(`route-upload-${prev.routeId}-line`, 'line-width', 3);
      map.setPaintProperty(`route-upload-${prev.routeId}-line`, 'line-opacity', 0.85);
    }
  }

  state.selectedIdx = idx;
  const route = state.routes[idx];

  // Restore full geojson (in case preview had trimmed it)
  map.getSource(`route-upload-${route.routeId}`)?.setData(route.geojson);

  // Highlight selected
  map.setPaintProperty(`route-upload-${route.routeId}-line`, 'line-width', 5);
  map.setPaintProperty(`route-upload-${route.routeId}-line`, 'line-opacity', 1.0);

  // Set as active route
  state.routeId     = route.routeId;
  state.routeSource = 'upload';
  state.startCoord  = route.startCoord;
  state.endCoord    = route.endCoord;

  if (route.startCoord) setCoord('start', route.startCoord);
  if (route.endCoord)   setCoord('end',   route.endCoord);
  if (elSelectedRouteLabel) elSelectedRouteLabel.textContent = route.filename;

  setEndpointsMode('upload');

  const [minx, miny, maxx, maxy] = route.bounds;
  map.fitBounds([[minx, miny], [maxx, maxy]], { padding: 60, duration: 500 });

  if (route.warnings?.length) setUploadWarnings(route.warnings);

  renderRouteList();
  showElevPanel(route);
  schedulePreview();
}

function removeRoute(idx) {
  const route = state.routes[idx];

  const srcId = `route-upload-${route.routeId}`;
  if (map.getLayer(`${srcId}-line`)) map.removeLayer(`${srcId}-line`);
  if (map.getSource(srcId))          map.removeSource(srcId);

  state.routes.splice(idx, 1);

  if (state.selectedIdx === idx) {
    state.selectedIdx = null;
    startMarker.remove();
    endMarker.remove();
    elInputStart.value = '';
    elInputEnd.value   = '';

    if (state.routes.length > 0) {
      selectRoute(Math.min(idx, state.routes.length - 1));
    } else {
      hideElevPanel();
      setEndpointsMode('draw');
      map.getSource('frames')?.setData(emptyFC());
      elPreviewInfo.classList.add('hidden');
      setPreviewWarnings([]);
      if (state.drawnRouteId) {
        state.routeId     = state.drawnRouteId;
        state.routeSource = 'drawn';
        state.startCoord  = state.waypoints[0] || null;
        state.endCoord    = state.waypoints[state.waypoints.length - 1] || null;
        schedulePreview();
      } else {
        state.routeId = null; state.routeSource = null;
        state.startCoord = null; state.endCoord = null;
        elBtnGenerate.disabled = true;
      }
    }
  } else if (state.selectedIdx !== null && state.selectedIdx > idx) {
    state.selectedIdx--;
  }

  renderRouteList();
  updateDropZone();
}

function renderRouteList() {
  elRouteList.innerHTML = '';
  state.routes.forEach((route, idx) => {
    const item = document.createElement('div');
    item.className = 'route-item' + (idx === state.selectedIdx ? ' selected' : '');
    item.style.setProperty('--route-color', route.color);

    const swatch = document.createElement('div');
    swatch.className = 'route-swatch';
    swatch.style.background = route.color;

    const name = document.createElement('span');
    name.className = 'route-item-name';
    name.textContent = route.filename;
    name.title = route.filename;

    const btn = document.createElement('button');
    btn.className = 'btn-icon';
    btn.textContent = '✕';
    btn.title = 'Remove route';
    btn.addEventListener('click', (e) => { e.stopPropagation(); removeRoute(idx); });

    item.appendChild(swatch);
    item.appendChild(name);
    item.appendChild(btn);
    item.addEventListener('click', () => selectRoute(idx));
    elRouteList.appendChild(item);
  });

  elRouteCountBadge.textContent = state.routes.length > 0 ? `(${state.routes.length}/5)` : '';
  updateDropZone();
}

function updateDropZone() {
  elDropZone.classList.toggle('hidden', state.routes.length >= 5);
}

// ── Elevation panel ────────────────────────────────────────────────────────
function showElevPanel(route) {
  elElevName.textContent = route.filename;
  const dist = route.distanceMiles.toFixed(1);
  elElevStats.textContent = `${dist} mi · +${Math.round(route.gainFt)} ft / −${Math.round(route.lossFt)} ft`;
  elElevPanel.classList.remove('hidden');
  requestAnimationFrame(() => drawElevationProfile(route));
}

function hideElevPanel() {
  elElevPanel.classList.add('hidden');
}

elElevClose.addEventListener('click', () => {
  hideElevPanel();
  if (state.selectedIdx !== null) {
    const prev = state.routes[state.selectedIdx];
    if (prev) {
      map.setPaintProperty(`route-upload-${prev.routeId}-line`, 'line-width', 3);
      map.setPaintProperty(`route-upload-${prev.routeId}-line`, 'line-opacity', 0.85);
    }
    state.selectedIdx = null;
    startMarker.remove();
    endMarker.remove();
    elInputStart.value = '';
    elInputEnd.value   = '';
    setEndpointsMode('draw');
    map.getSource('frames')?.setData(emptyFC());
    elPreviewInfo.classList.add('hidden');
    setPreviewWarnings([]);
    if (state.drawnRouteId) {
      state.routeId = state.drawnRouteId;
      state.routeSource = 'drawn';
    } else {
      state.routeId = null; state.routeSource = null;
      elBtnGenerate.disabled = true;
    }
    renderRouteList();
  }
});

function drawElevationProfile(route) {
  const ctx  = elElevCanvas.getContext('2d');
  const dpr  = window.devicePixelRatio || 1;
  const W    = elElevPanel.clientWidth;
  const H    = elElevPanel.offsetHeight - document.getElementById('elev-header').offsetHeight;
  elElevCanvas.width        = W * dpr;
  elElevCanvas.height       = Math.max(H, 10) * dpr;
  elElevCanvas.style.width  = W + 'px';
  elElevCanvas.style.height = Math.max(H, 10) + 'px';
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);

  const prof = route.elevationProfile;
  if (!prof || prof.length < 2) {
    ctx.fillStyle = '#666'; ctx.font = '12px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('No elevation data available', W / 2, H / 2);
    return;
  }

  const PAD = { top: 10, right: 14, bottom: 26, left: 44 };
  const cW = W - PAD.left - PAD.right;
  const cH = H - PAD.top  - PAD.bottom;

  const maxDist   = prof[prof.length - 1].distance_m;
  const elevs     = prof.map(p => p.elevation_ft);
  const minElev   = Math.min(...elevs);
  const maxElev   = Math.max(...elevs);
  const elevRange = (maxElev - minElev) || 1;

  const xS = d => PAD.left + (d / maxDist) * cW;
  const yS = e => PAD.top  + cH - ((e - minElev) / elevRange) * cH;

  // Area fill with gradient
  const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + cH);
  grad.addColorStop(0, route.color + 'bb');
  grad.addColorStop(1, route.color + '22');
  ctx.beginPath();
  ctx.moveTo(xS(prof[0].distance_m), yS(prof[0].elevation_ft));
  for (let i = 1; i < prof.length; i++) ctx.lineTo(xS(prof[i].distance_m), yS(prof[i].elevation_ft));
  ctx.lineTo(xS(maxDist), PAD.top + cH);
  ctx.lineTo(xS(0), PAD.top + cH);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // Profile line
  ctx.beginPath();
  ctx.moveTo(xS(prof[0].distance_m), yS(prof[0].elevation_ft));
  for (let i = 1; i < prof.length; i++) ctx.lineTo(xS(prof[i].distance_m), yS(prof[i].elevation_ft));
  ctx.strokeStyle = route.color; ctx.lineWidth = 1.5; ctx.stroke();

  // Axes
  ctx.strokeStyle = '#444'; ctx.lineWidth = 1; ctx.setLineDash([]);
  ctx.beginPath();
  ctx.moveTo(PAD.left, PAD.top); ctx.lineTo(PAD.left, PAD.top + cH);
  ctx.moveTo(PAD.left, PAD.top + cH); ctx.lineTo(PAD.left + cW, PAD.top + cH);
  ctx.stroke();

  // Y gridlines + labels
  ctx.font = '9px system-ui'; ctx.textBaseline = 'middle'; ctx.textAlign = 'right';
  for (let i = 0; i <= 3; i++) {
    const e = minElev + (i / 3) * elevRange;
    const y = yS(e);
    ctx.fillStyle = '#888'; ctx.fillText(Math.round(e) + 'ft', PAD.left - 4, y);
    ctx.strokeStyle = '#333'; ctx.lineWidth = 0.5; ctx.setLineDash([2, 3]);
    ctx.beginPath(); ctx.moveTo(PAD.left + 1, y); ctx.lineTo(PAD.left + cW, y); ctx.stroke();
    ctx.setLineDash([]);
  }

  // X labels (miles)
  ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.fillStyle = '#888';
  const xN = Math.min(5, Math.max(2, Math.floor(route.distanceMiles)));
  for (let i = 0; i <= xN; i++) {
    const d = (i / xN) * maxDist;
    ctx.fillText((d / 1609.344).toFixed(1) + 'mi', xS(d), PAD.top + cH + 5);
  }
}

// ── Draw mode: multi-waypoint ──────────────────────────────────────────────
async function addWaypoint(latlon) {
  if (state.isFetchingSegment) return;

  const isFirst      = state.waypoints.length === 0;
  const prevWaypoint = isFirst ? null : state.waypoints[state.waypoints.length - 1];

  state.waypoints.push(latlon);
  state.redoStack = [];
  updateDrawDisplay();

  if (!isFirst) {
    if (getDrawMode() === 'freehand') {
      state.segmentCoords.push([[prevWaypoint[1], prevWaypoint[0]], [latlon[1], latlon[0]]]);
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
        state.waypoints.pop();
        state.redoStack = [];
        updateDrawDisplay();
        setUploadWarnings([err.message]);
        return;
      } finally {
        state.isFetchingSegment = false;
        map.getCanvas().style.cursor = state.selectedIdx === null ? 'crosshair' : '';
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
  const seg = state.segmentCoords.length  > 0 ? state.segmentCoords.pop()  : null;
  const det = state.segmentDetoured.length > 0 ? state.segmentDetoured.pop() : false;
  state.redoStack.push({ wp, seg, det });

  updateDrawDisplay();
  updateRouteLineFromSegments();
  map.getSource('frames').setData(emptyFC());

  if (state.segmentCoords.length > 0) {
    scheduleCommit();
  } else {
    state.drawnRouteId = null;
    if (state.routeSource === 'drawn') {
      state.routeId = null; state.routeSource = null;
      elPreviewInfo.classList.add('hidden');
      setPreviewWarnings([]);
      elBtnGenerate.disabled = true;
    }
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
  const n = state.waypoints.length;
  const features = state.waypoints.map((wp, i) => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [wp[1], wp[0]] },
    properties: { isFirst: i === 0, isLast: i === n - 1 && n > 1, idx: i + 1 },
  }));
  map.getSource('waypoints')?.setData({ type: 'FeatureCollection', features });

  if (n > 0) {
    const s = state.segmentCoords.length;
    const d = state.segmentDetoured.filter(Boolean).length;
    elDrawWpCount.textContent = `${n} waypoint${n !== 1 ? 's' : ''} · ${s} segment${s !== 1 ? 's' : ''}${d > 0 ? ` · ${d} straight-line` : ''}`;
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
  map.getSource('route')?.setData(
    coords.length >= 2
      ? { type: 'Feature', geometry: { type: 'LineString', coordinates: coords }, properties: {} }
      : emptyFC()
  );

  const detourFeatures = state.segmentCoords
    .filter((_, i) => state.segmentDetoured[i])
    .map(seg => ({ type: 'Feature', geometry: { type: 'LineString', coordinates: seg }, properties: {} }));
  map.getSource('route-detour')?.setData({ type: 'FeatureCollection', features: detourFeatures });
}

function getCombinedCoords() {
  if (state.segmentCoords.length === 0) return [];
  const out = [...state.segmentCoords[0]];
  for (let i = 1; i < state.segmentCoords.length; i++) out.push(...state.segmentCoords[i].slice(1));
  return out;
}

// ── Commit drawn route ─────────────────────────────────────────────────────
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

    state.drawnRouteId = data.route_id;

    // Only take over as active route if no upload is selected
    if (state.selectedIdx === null) {
      state.routeId     = data.route_id;
      state.routeSource = 'drawn';
      state.startCoord  = state.waypoints[0];
      state.endCoord    = state.waypoints[state.waypoints.length - 1];
      runPreview();
    }
  } catch (err) {
    setPreviewWarnings([`Failed to save route: ${err.message}`]);
  }
}

// ── Undo / redo ────────────────────────────────────────────────────────────
elBtnUndo.addEventListener('click', undoWaypoint);
elBtnRedo.addEventListener('click', redoWaypoint);

document.addEventListener('keydown', (e) => {
  const mod = e.ctrlKey || e.metaKey;
  if (!mod) return;
  if (e.key === 'z' && !e.shiftKey)                   { e.preventDefault(); undoWaypoint(); }
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
  if (state.startCoord && state.endCoord) {
    if (state.selectedIdx !== null) {
      state.routes[state.selectedIdx].startCoord = state.startCoord;
      state.routes[state.selectedIdx].endCoord   = state.endCoord;
    }
    schedulePreview();
  }
}

// ── Settings changes ───────────────────────────────────────────────────────
[elSelScale, elSelPaper, elInpOverlap, elInpUtmZone].forEach(el => {
  el.addEventListener('change', () => { if (state.routeId) schedulePreview(); });
});
document.getElementById('lyr-bw').addEventListener('change', () => { if (state.routeId) schedulePreview(); });

// ── Preview ────────────────────────────────────────────────────────────────
function schedulePreview() {
  clearTimeout(state.previewDebounce);
  state.previewDebounce = setTimeout(runPreview, 400);
}

async function runPreview() {
  if (!state.routeId) return;

  let start, end;
  if (state.routeSource === 'upload') {
    if (!state.startCoord || !state.endCoord) return;
    start = state.startCoord; end = state.endCoord;
  } else {
    if (state.waypoints.length < 2) return;
    start = state.waypoints[0]; end = state.waypoints[state.waypoints.length - 1];
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

  if (state.routeSource === 'upload' && data.route_geojson && state.selectedIdx !== null) {
    const r = state.routes[state.selectedIdx];
    map.getSource(`route-upload-${r.routeId}`)?.setData(data.route_geojson);
  } else if (state.routeSource === 'drawn' && data.route_geojson) {
    map.getSource('route')?.setData(data.route_geojson);
  }

  map.getSource('frames').setData(data.frames);
  elPreviewPages.textContent = `${data.page_count} page${data.page_count !== 1 ? 's' : ''}`;
  elPreviewMiles.textContent = `${data.length_miles} mi`;
  elPreviewInfo.classList.remove('hidden');
  setPreviewWarnings(data.warnings?.length ? data.warnings : []);
  elBtnGenerate.disabled = false;
}

// ── Export ─────────────────────────────────────────────────────────────────
document.getElementById('btn-save-gpx').addEventListener('click',     () => triggerExport('gpx'));
document.getElementById('btn-save-geojson').addEventListener('click', () => triggerExport('geojson'));

function getOutputName() {
  const raw  = document.getElementById('inp-filename').value.trim();
  const safe = raw.replace(/[^\w\s\-]/g, '').replace(/\s+/g, ' ').trim();
  return safe || 'trail_map';
}

function triggerExport(fmt) {
  if (!state.routeId) return;
  const a = document.createElement('a');
  a.href = `/api/export/${state.routeId}/${fmt}`; a.download = `${getOutputName()}.${fmt}`; a.click();
}

// ── Generate PDF ───────────────────────────────────────────────────────────
elBtnGenerate.addEventListener('click', async () => {
  if (!state.routeId) return;

  let start, end;
  if (state.routeSource === 'upload') { start = state.startCoord; end = state.endCoord; }
  else { start = state.waypoints[0]; end = state.waypoints[state.waypoints.length - 1]; }

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
    const url  = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = `${getOutputName()}.pdf`; a.click();
    URL.revokeObjectURL(url);
    showStatus('✓ PDF downloaded', false);
  } catch (err) {
    showStatus(err.message, true);
  } finally {
    elBtnGenerate.disabled = false;
    elGenProgress.classList.add('hidden');
  }
});

// ── Reverse route ──────────────────────────────────────────────────────────
document.getElementById('btn-reverse-route').addEventListener('click', reverseRoute);

function reverseRoute() {
  if (!state.routeId) return;

  if (state.routeSource === 'upload' && state.selectedIdx !== null) {
    const route = state.routes[state.selectedIdx];
    [route.startCoord, route.endCoord] = [route.endCoord, route.startCoord];
    state.startCoord = route.startCoord;
    state.endCoord   = route.endCoord;
    if (route.startCoord) setCoord('start', route.startCoord);
    if (route.endCoord)   setCoord('end',   route.endCoord);
    onUploadCoordsChanged();
  } else if (state.routeSource === 'drawn') {
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

// ── Clear drawing ──────────────────────────────────────────────────────────
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

// ── UI helpers ─────────────────────────────────────────────────────────────
function setEndpointsMode(mode) {
  elEpUpload.classList.toggle('hidden', mode !== 'upload');
  elEpDraw.classList.toggle('hidden',   mode !== 'draw');
  if (mode !== 'upload') cancelPickMode();
}

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
    toast.id = 'detour-toast'; toast.className = 'detour-toast';
    document.body.appendChild(toast);
  }
  toast.textContent = 'Trail routing unavailable here — segment shown as straight line (orange dashed). Add more waypoints or switch to Freehand.';
  toast.classList.add('visible');
  clearTimeout(_detourToastTimer);
  _detourToastTimer = setTimeout(() => toast.classList.remove('visible'), 6000);
}
