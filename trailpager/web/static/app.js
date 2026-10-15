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
  dragRotate: false, // 3D pitch/rotate is opt-in via the settings toggle
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

map.on('load', async () => {
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

  // ── Terrain DEM — Mapzen/AWS terrarium tiles (elevation queries + hillshade)
  map.addSource('terrain-dem', {
    type: 'raster-dem',
    tiles: ['/api/terrain/{z}/{x}/{y}.png'],
    encoding: 'terrarium',
    tileSize: 256,
    maxzoom: 15,
    attribution: '© Mapzen, USGS, SRTM',
  });
  map.setTerrain({ source: 'terrain-dem', exaggeration: 1 });

  map.addLayer({
    id: 'terrain-hillshade',
    type: 'hillshade',
    source: 'terrain-dem',
    paint: {
      'hillshade-exaggeration': 0.35,
      'hillshade-illumination-direction': 315,
      'hillshade-shadow-color': '#000000',
      'hillshade-highlight-color': '#ffffff',
    },
  }, 'route-line');

  // ── Client-side vector contours via maplibre-contour (100 ft intervals, zoom ≥ 15)
  // zoom 15 ≈ scale bar showing ≤ 1000 ft at US latitudes
  try {
    const mod = await import('https://esm.sh/maplibre-contour');
    const DemSource = mod.DemSource || (mod.default && mod.default.DemSource);
    if (!DemSource) throw new Error('DemSource not found in maplibre-contour module');

    const demContour = new DemSource({
      url: '/api/terrain/{z}/{x}/{y}.png',
      encoding: 'terrarium',
      maxzoom: 15,
      worker: false,
    });
    // setupMaplibre requires the maplibregl global, not the map instance
    demContour.setupMaplibre(maplibregl);

    map.addSource('contours', {
      type: 'vector',
      tiles: [demContour.contourProtocolUrl({
        multiplier: 3.28084,   // elevations in feet → thresholds in feet
        thresholds: {
          15: [100, 500],      // 100 ft minor, 500 ft (index) major
        },
      })],
      maxzoom: 15,
    });
    map.addLayer({
      id: 'contours-layer',
      type: 'line',
      source: 'contours',
      'source-layer': 'contours',
      minzoom: 15,
      filter: ['==', ['get', 'level'], 0],
      paint: {
        'line-color': '#7a5c2e',
        'line-width': 0.6,
        'line-opacity': 0.65,
      },
    }, 'route-line');
    map.addLayer({
      id: 'contours-major-layer',
      type: 'line',
      source: 'contours',
      'source-layer': 'contours',
      minzoom: 15,
      filter: ['==', ['get', 'level'], 1],
      paint: {
        'line-color': '#5a3e14',
        'line-width': 1.2,
        'line-opacity': 0.85,
      },
    }, 'route-line');
    map.addLayer({
      id: 'contours-label-layer',
      type: 'symbol',
      source: 'contours',
      'source-layer': 'contours',
      minzoom: 15,
      filter: ['==', ['get', 'level'], 1],
      layout: {
        'symbol-placement': 'line',
        'text-field': ['concat', ['to-string', ['get', 'ele']], ' ft'],
        'text-size': 9,
        'text-font': ['Open Sans Regular', 'Arial Unicode MS Regular'],
        'text-max-angle': 30,
        'text-pitch-alignment': 'map',
        'text-rotation-alignment': 'map',
      },
      paint: {
        'text-color': '#5a3e14',
        'text-halo-color': 'rgba(255,255,255,0.8)',
        'text-halo-width': 1.2,
      },
    }, 'route-line');
  } catch (err) {
    console.warn('maplibre-contour unavailable, contours disabled:', err);
  }
});

// ── Map click dispatcher ───────────────────────────────────────────────────
map.on('click', (e) => {
  const { lat, lng } = e.lngLat;
  if (state.pickMode) {
    setCoord(state.pickMode, [lat, lng]);
    cancelPickMode();
    onUploadCoordsChanged();
  } else if (_selectedDrawnRoute()) {
    addWaypoint([lat, lng]);
  }
});

map.on('mousemove', () => {
  if (!state.pickMode && _selectedDrawnRoute() && !state.isFetchingSegment) {
    map.getCanvas().style.cursor = 'crosshair';
  } else if (!state.pickMode) {
    map.getCanvas().style.cursor = '';
  }
});

function _selectedDrawnRoute() {
  if (state.selectedIdx === null) return null;
  const r = state.routes[state.selectedIdx];
  return r?.kind === 'drawn' ? r : null;
}

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
const elElevFetching       = document.getElementById('elev-fetching');
const elElevTab            = document.getElementById('elev-tab');
const elElevTabStats       = document.getElementById('elev-tab-stats');

// Elevation profile cursor (map marker + chart crosshair)
let _elevCursorFrac  = null;
let _elevCursorRafId = null;
const _elevCursorEl  = (() => { const el = document.createElement('div'); el.className = 'elev-cursor-pin'; return el; })();
const _elevCursorMarker = new maplibregl.Marker({ element: _elevCursorEl, anchor: 'center' });

const elBtnSettings        = document.getElementById('btn-settings');
const elSettingsDrawer     = document.getElementById('settings-drawer');
const elSidebarBody        = document.getElementById('sidebar-body');

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

// ── Settings drawer toggle ─────────────────────────────────────────────────
elBtnSettings.addEventListener('click', () => {
  const isOpen = !elSettingsDrawer.classList.contains('hidden');
  elSettingsDrawer.classList.toggle('hidden', isOpen);
  elSidebarBody.classList.toggle('hidden', !isOpen);
  elBtnSettings.style.color = isOpen ? '' : 'var(--accent)';
});

// ── DOM refs (draw endpoints) ──────────────────────────────────────────────
const elDrawEndpoints  = document.getElementById('draw-endpoints');
const elDrawStartCoord = document.getElementById('draw-start-coord');
const elDrawEndCoord   = document.getElementById('draw-end-coord');
const elBtnReverseDraw = document.getElementById('btn-reverse-drawn');

// ── Upload-mode markers ────────────────────────────────────────────────────
function makeMarkerEl(color) {
  const el = document.createElement('div');
  el.style.cssText = `width:14px;height:14px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.5);cursor:grab`;
  return el;
}

// ── Drawn-route start / end pin markers ────────────────────────────────────
function _makeDrawnPinEl(color) {
  const el = document.createElement('div');
  el.style.cssText = `width:16px;height:16px;border-radius:50%;background:${color};border:2.5px solid #fff;box-shadow:0 2px 7px rgba(0,0,0,.6)`;
  return el;
}
const drawnStartMarker = new maplibregl.Marker({ element: _makeDrawnPinEl('#27ae60'), anchor: 'center' });
const drawnEndMarker   = new maplibregl.Marker({ element: _makeDrawnPinEl('#c0392b'), anchor: 'center' });
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

  // Clear orphaned drawing state (no drawn route in the list)
  const hasDrawnRoute = state.routes.some(r => r.kind === 'drawn');
  if (!hasDrawnRoute && state.waypoints.length > 0) {
    clearDrawing();
    state.drawnRouteId = null;
  }

  const route = {
    routeId:          data.route_id,
    kind:             'upload',
    filename:         file.name.replace(/\.[^.]+$/, ''),
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

  // Auto-select first uploaded route if nothing is active
  if (state.selectedIdx === null) selectRoute(state.routes.length - 1);
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
  // Save / deselect previous
  if (state.selectedIdx !== null) {
    const prev = state.routes[state.selectedIdx];
    if (prev?.kind === 'drawn') {
      _saveDrawnState(prev);
      _syncDrawnLayer(prev);
    } else if (prev?.kind === 'upload') {
      map.setPaintProperty(`route-upload-${prev.routeId}-line`, 'line-width', 3);
      map.setPaintProperty(`route-upload-${prev.routeId}-line`, 'line-opacity', 0.85);
    }
  }

  state.selectedIdx = idx;
  const route = state.routes[idx];

  if (route.kind === 'drawn') {
    _loadDrawnState(route);
    state.routeId     = route.routeId;
    state.routeSource = route.routeId ? 'drawn' : null;
    state.startCoord  = route.startCoord;
    state.endCoord    = route.endCoord;

    map.setPaintProperty('route-line', 'line-color', route.color);
    const permId = `route-drawn-${route.routeId}-line`;
    if (map.getLayer(permId)) map.setPaintProperty(permId, 'line-opacity', 0);

    updateRouteLineFromSegments();
    updateDrawDisplay();
    setEndpointsMode('draw');
    if (route.elevationProfile?.length >= 2) showElevPanel(route);
    else hideElevPanel();
    if (route.bounds) {
      const [minx, miny, maxx, maxy] = route.bounds;
      map.fitBounds([[minx, miny], [maxx, maxy]], { padding: 60, duration: 500 });
    }
    if (route.routeId) schedulePreview();

  } else {
    // Upload route
    map.getSource(`route-upload-${route.routeId}`)?.setData(route.geojson);
    map.setPaintProperty(`route-upload-${route.routeId}-line`, 'line-width', 5);
    map.setPaintProperty(`route-upload-${route.routeId}-line`, 'line-opacity', 1.0);

    state.routeId     = route.routeId;
    state.routeSource = 'upload';
    state.startCoord  = route.startCoord;
    state.endCoord    = route.endCoord;

    if (route.startCoord) setCoord('start', route.startCoord);
    if (route.endCoord)   setCoord('end',   route.endCoord);
    if (elSelectedRouteLabel) elSelectedRouteLabel.textContent = route.filename;

    // Clear the shared drawing canvas so the drawn-route line doesn't linger
    map.getSource('waypoints')?.setData(emptyFC());
    map.getSource('route')?.setData(emptyFC());
    map.getSource('route-detour')?.setData(emptyFC());

    setEndpointsMode('upload');

    const [minx, miny, maxx, maxy] = route.bounds;
    map.fitBounds([[minx, miny], [maxx, maxy]], { padding: 60, duration: 500 });

    if (route.warnings?.length) setUploadWarnings(route.warnings);

    showElevPanel(route);
    schedulePreview();
  }

  renderRouteList();
}

function _saveDrawnState(route) {
  route._waypoints       = [...state.waypoints];
  route._segmentCoords   = state.segmentCoords.map(s => [...s]);
  route._segmentDetoured = [...state.segmentDetoured];
}

function _loadDrawnState(route) {
  state.waypoints       = [...(route._waypoints       || [])];
  state.segmentCoords   = (route._segmentCoords || []).map(s => [...s]);
  state.segmentDetoured = [...(route._segmentDetoured || [])];
  state.redoStack       = [];
}

function _syncDrawnLayer(route) {
  if (!route.routeId) return;
  const coords = getCombinedCoords();
  if (coords.length < 2) return;
  const srcId  = `route-drawn-${route.routeId}`;
  const gj     = { type: 'Feature', geometry: { type: 'LineString', coordinates: coords }, properties: {} };
  if (map.getSource(srcId)) {
    map.getSource(srcId).setData(gj);
  } else {
    map.addSource(srcId, { type: 'geojson', data: gj });
    map.addLayer({
      id: `${srcId}-line`, type: 'line', source: srcId,
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: { 'line-color': route.color, 'line-width': 3, 'line-opacity': 0.85 },
    });
  }
  map.setPaintProperty(`${srcId}-line`, 'line-opacity', 0.85);
  map.getSource('waypoints')?.setData(emptyFC());
  map.getSource('route')?.setData(emptyFC());
  map.getSource('route-detour')?.setData(emptyFC());
  drawnStartMarker.remove();
  drawnEndMarker.remove();
}

function addDrawnRoute() {
  if (state.routes.length >= 5) return;
  const usedColors = new Set(state.routes.map(r => r.color));
  const color = _COLOR_PALETTE.find(c => !usedColors.has(c)) || _COLOR_PALETTE[state.routes.length % _COLOR_PALETTE.length];
  const route = {
    kind:             'drawn',
    routeId:          null,
    filename:         'New Route',
    color,
    geojson:          null,
    bounds:           null,
    startCoord:       null,
    endCoord:         null,
    elevationProfile: [],
    distanceMiles:    0,
    gainFt:           0,
    lossFt:           0,
    warnings:         [],
    _waypoints:       [],
    _segmentCoords:   [],
    _segmentDetoured: [],
  };
  state.routes.push(route);
  selectRoute(state.routes.length - 1);
}

function removeRoute(idx) {
  const route = state.routes[idx];

  if (route.kind === 'drawn') {
    const permSrc = `route-drawn-${route.routeId}`;
    if (map.getLayer(`${permSrc}-line`)) map.removeLayer(`${permSrc}-line`);
    if (map.getSource(permSrc))          map.removeSource(permSrc);
    if (state.selectedIdx === idx) {
      map.getSource('waypoints')?.setData(emptyFC());
      map.getSource('route')?.setData(emptyFC());
      map.getSource('route-detour')?.setData(emptyFC());
      drawnStartMarker.remove();
      drawnEndMarker.remove();
    }
  } else {
    const srcId = `route-upload-${route.routeId}`;
    if (map.getLayer(`${srcId}-line`)) map.removeLayer(`${srcId}-line`);
    if (map.getSource(srcId))          map.removeSource(srcId);
  }

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
      state.routeId = null; state.routeSource = null;
      state.startCoord = null; state.endCoord = null;
      state.waypoints = []; state.segmentCoords = []; state.segmentDetoured = [];
      updateDrawDisplay();
      elBtnGenerate.disabled = true;
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
    swatch.addEventListener('click', (e) => { e.stopPropagation(); showColorPicker(swatch, idx); });

    const name = document.createElement('span');
    name.className = 'route-item-name';
    name.textContent = route.filename;
    name.title = route.filename;

    const editBtn = document.createElement('button');
    editBtn.className = 'btn-icon btn-edit';
    editBtn.innerHTML = '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M11 2.5l2.5 2.5L5 13.5H2.5V11L11 2.5z"/><path d="M9.5 4l2.5 2.5"/></svg>';
    editBtn.title = 'Rename';
    editBtn.addEventListener('click', (e) => { e.stopPropagation(); startRename(item, name, idx); });

    const removeBtn = document.createElement('button');
    removeBtn.className = 'btn-icon';
    removeBtn.textContent = '✕';
    removeBtn.title = 'Remove route';
    removeBtn.addEventListener('click', (e) => { e.stopPropagation(); removeRoute(idx); });

    item.appendChild(swatch);
    item.appendChild(name);
    item.appendChild(editBtn);
    item.appendChild(removeBtn);
    item.addEventListener('click', () => selectRoute(idx));
    elRouteList.appendChild(item);
  });

  if (state.routes.length < 5) {
    const addBtn = document.createElement('div');
    addBtn.className = 'route-add-btn';
    addBtn.title = 'Draw a new route';
    addBtn.textContent = '+';
    addBtn.addEventListener('click', addDrawnRoute);
    elRouteList.appendChild(addBtn);
  }

  elRouteCountBadge.textContent = state.routes.length > 0 ? `(${state.routes.length}/5)` : '';
  updateDropZone();
}

function startRename(item, nameSpan, idx) {
  const inp = document.createElement('input');
  inp.className = 'route-item-edit';
  inp.value = state.routes[idx].filename;
  inp.maxLength = 80;

  item.replaceChild(inp, nameSpan);
  inp.focus();
  inp.select();

  function commit() {
    const val = inp.value.replace(/[^\w\s\-]/g, '').replace(/\s+/g, ' ').trim();
    if (val) state.routes[idx].filename = val;
    renderRouteList();
    if (elElevName && idx === state.selectedIdx) elElevName.textContent = state.routes[idx].filename;
  }

  inp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter')  { e.preventDefault(); commit(); }
    if (e.key === 'Escape') { e.preventDefault(); renderRouteList(); }
    e.stopPropagation();
  });
  inp.addEventListener('blur', commit);
  inp.addEventListener('click', (e) => e.stopPropagation());
}

function updateDropZone() {
  elDropZone.classList.toggle('hidden', state.routes.length >= 5);
}

// ── Color picker ───────────────────────────────────────────────────────────
const _COLOR_PALETTE = [
  '#e74c3c', '#e67e22', '#f39c12', '#f1c40f',
  '#2ecc71', '#1abc9c', '#3498db', '#2980b9',
  '#9b59b6', '#e91e63', '#795548', '#607d8b',
];

function showColorPicker(swatchEl, idx) {
  closeColorPicker();

  const popup = document.createElement('div');
  popup.id = 'color-picker-popup';
  popup.className = 'color-picker-popup';

  _COLOR_PALETTE.forEach(color => {
    const dot = document.createElement('button');
    dot.className = 'color-picker-dot' + (color === state.routes[idx].color ? ' active' : '');
    dot.style.background = color;
    dot.title = color;
    dot.addEventListener('click', (e) => { e.stopPropagation(); applyRouteColor(idx, color); closeColorPicker(); });
    popup.appendChild(dot);
  });

  document.body.appendChild(popup);

  const r = swatchEl.getBoundingClientRect();
  let top = r.bottom + 6;
  if (top + 90 > window.innerHeight) top = r.top - 96;
  popup.style.left = Math.max(8, r.left) + 'px';
  popup.style.top  = top + 'px';

  setTimeout(() => document.addEventListener('click', _closePickerOutside), 0);
}

function _closePickerOutside(e) {
  const popup = document.getElementById('color-picker-popup');
  if (popup && !popup.contains(e.target)) closeColorPicker();
}

function closeColorPicker() {
  document.getElementById('color-picker-popup')?.remove();
  document.removeEventListener('click', _closePickerOutside);
}

function applyRouteColor(idx, color) {
  state.routes[idx].color = color;
  const route = state.routes[idx];
  if (route.kind === 'drawn') {
    if (idx === state.selectedIdx) map.setPaintProperty('route-line', 'line-color', color);
    const permId = `route-drawn-${route.routeId}-line`;
    if (map.getLayer(permId)) map.setPaintProperty(permId, 'line-color', color);
  } else {
    const layerId = `route-upload-${route.routeId}-line`;
    if (map.getLayer(layerId)) map.setPaintProperty(layerId, 'line-color', color);
    if (idx === state.selectedIdx) showElevPanel(route);
  }
  renderRouteList();
}

// ── Elevation panel ────────────────────────────────────────────────────────
function showElevPanel(route) {
  elElevName.textContent = route.filename;
  const dist = (route.distanceMiles || 0).toFixed(1);
  elElevStats.textContent = dist > 0
    ? `${dist} mi · +${Math.round(route.gainFt)} ft / −${Math.round(route.lossFt)} ft`
    : '';
  elElevPanel.classList.remove('hidden');
  updateElevTab();
  requestAnimationFrame(() => drawElevationProfile(route));
}

function hideElevPanel() {
  _elevCursorFrac = null;
  _elevCursorMarker.remove();
  elElevPanel.classList.add('hidden');
  updateElevTab();
}

function updateElevTab() {
  const panelHidden = elElevPanel.classList.contains('hidden');
  if (!panelHidden) { elElevTab.classList.add('hidden'); return; }
  const route = state.selectedIdx !== null ? state.routes[state.selectedIdx] : null;
  const hasData = route && route.elevationProfile && route.elevationProfile.length >= 2;
  elElevTab.classList.toggle('hidden', !hasData);
  if (hasData && route) {
    const dist = (route.distanceMiles || 0).toFixed(1);
    elElevTabStats.textContent = dist > 0 ? `${dist} mi` : '';
  }
}

elElevClose.addEventListener('click', () => hideElevPanel());

elElevTab.addEventListener('click', () => {
  const route = state.selectedIdx !== null ? state.routes[state.selectedIdx] : null;
  if (route) showElevPanel(route);
});

async function fetchDrawnRouteElevation(route, coords) {
  route._elevFetchVer = (route._elevFetchVer || 0) + 1;
  const myVer = route._elevFetchVer;

  // Show panel with loading state
  if (state.routes[state.selectedIdx] === route) {
    elElevName.textContent  = route.filename;
    elElevStats.textContent = '';
    elElevFetching.classList.remove('hidden');
    elElevPanel.classList.remove('hidden');
    updateElevTab();
  }

  try {
    const res = await fetch('/api/elevation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ coordinates: coords }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Elevation fetch failed');

    if (route._elevFetchVer !== myVer) return; // stale response

    route.elevationProfile = data.elevation_profile;
    route.distanceMiles    = data.total_distance_miles;
    route.gainFt           = data.gain_ft;
    route.lossFt           = data.loss_ft;

    if (state.routes[state.selectedIdx] === route) showElevPanel(route);
  } catch (_err) {
    // silently ignore — profile will just show "No elevation data"
  } finally {
    elElevFetching.classList.add('hidden');
  }
}

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

  // Cursor overlay: vertical line + dot on profile curve
  if (_elevCursorFrac !== null) {
    const cx = xS(_elevCursorFrac * maxDist);
    ctx.save();
    ctx.strokeStyle = 'rgba(120,120,120,0.65)';
    ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(cx, PAD.top); ctx.lineTo(cx, PAD.top + cH); ctx.stroke();
    ctx.setLineDash([]);
    const cy = yS(_elevAtFrac(prof, _elevCursorFrac));
    ctx.beginPath(); ctx.arc(cx, cy, 4.5, 0, Math.PI * 2);
    ctx.fillStyle = '#fff'; ctx.fill();
    ctx.strokeStyle = route.color; ctx.lineWidth = 2; ctx.stroke();
    ctx.restore();
  }
}

// ── Elevation profile ↔ map cursor ────────────────────────────────────────

// Interpolate elevation_ft at a 0-1 fraction along the profile
function _elevAtFrac(prof, frac) {
  const maxD = prof[prof.length - 1].distance_m;
  const target = frac * maxD;
  let lo = 0, hi = prof.length - 1;
  while (lo < hi - 1) { const mid = (lo + hi) >> 1; if (prof[mid].distance_m <= target) lo = mid; else hi = mid; }
  const span = prof[lo + 1].distance_m - prof[lo].distance_m;
  if (span === 0) return prof[lo].elevation_ft;
  return prof[lo].elevation_ft + ((target - prof[lo].distance_m) / span) * (prof[lo + 1].elevation_ft - prof[lo].elevation_ft);
}

// Extract [lng, lat] coordinate array from a route (both upload and drawn)
function _routeLineCoords(route) {
  if (route.kind === 'drawn') {
    const isSelected = state.selectedIdx !== null && state.routes[state.selectedIdx] === route;
    const segs = isSelected ? state.segmentCoords : (route._segmentCoords || []);
    if (!segs.length) return null;
    const out = [...segs[0]];
    for (let i = 1; i < segs.length; i++) out.push(...segs[i].slice(1));
    return out.length >= 2 ? out : null;
  }
  if (!route.geojson) return null;
  const features = route.geojson.type === 'FeatureCollection' ? route.geojson.features
    : route.geojson.type === 'Feature' ? [route.geojson] : [];
  const line = features.find(f => f.geometry &&
    (f.geometry.type === 'LineString' || f.geometry.type === 'MultiLineString'));
  if (!line) return null;
  return line.geometry.type === 'LineString'
    ? line.geometry.coordinates
    : line.geometry.coordinates.flat();
}

function _haversineM(c1, c2) {
  const R = 6371000, r = Math.PI / 180;
  const dLat = (c2[1] - c1[1]) * r, dLon = (c2[0] - c1[0]) * r;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(c1[1] * r) * Math.cos(c2[1] * r) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// Return [lng, lat] on the route at a 0-1 fraction of its total length
function _routeCoordAtFrac(route, frac) {
  const coords = _routeLineCoords(route);
  if (!coords || coords.length < 2) return null;
  // Cache cumulative distances keyed by coord count (invalidates when route changes)
  if (!route._ccache || route._ccache.n !== coords.length) {
    const dists = [0];
    for (let i = 1; i < coords.length; i++)
      dists.push(dists[i - 1] + _haversineM(coords[i - 1], coords[i]));
    route._ccache = { n: coords.length, dists };
  }
  const { dists } = route._ccache;
  const total = dists[dists.length - 1];
  if (total === 0) return coords[0].slice(0, 2);
  const target = frac * total;
  let lo = 0, hi = dists.length - 1;
  while (lo < hi - 1) { const mid = (lo + hi) >> 1; if (dists[mid] <= target) lo = mid; else hi = mid; }
  const span = dists[lo + 1] - dists[lo];
  const t = span > 0 ? Math.min(1, (target - dists[lo]) / span) : 0;
  return [coords[lo][0] + t * (coords[lo + 1][0] - coords[lo][0]),
          coords[lo][1] + t * (coords[lo + 1][1] - coords[lo][1])];
}

const _ELEV_PAD_L = 44, _ELEV_PAD_R = 14; // must match PAD in drawElevationProfile

elElevCanvas.addEventListener('mousemove', (e) => {
  const route = state.selectedIdx !== null ? state.routes[state.selectedIdx] : null;
  if (!route?.elevationProfile?.length || route.elevationProfile.length < 2) return;
  const rect = elElevCanvas.getBoundingClientRect();
  const frac = Math.max(0, Math.min(1, (e.clientX - rect.left - _ELEV_PAD_L) / (rect.width - _ELEV_PAD_L - _ELEV_PAD_R)));
  // Update map marker position
  const lngLat = _routeCoordAtFrac(route, frac);
  if (lngLat) _elevCursorMarker.setLngLat(lngLat).addTo(map);
  // Redraw chart with cursor (throttled to rAF)
  if (_elevCursorFrac === frac) return;
  _elevCursorFrac = frac;
  if (_elevCursorRafId) cancelAnimationFrame(_elevCursorRafId);
  _elevCursorRafId = requestAnimationFrame(() => { drawElevationProfile(route); _elevCursorRafId = null; });
});

elElevCanvas.addEventListener('mouseleave', () => {
  _elevCursorFrac = null;
  _elevCursorMarker.remove();
  const route = state.selectedIdx !== null ? state.routes[state.selectedIdx] : null;
  if (route) requestAnimationFrame(() => drawElevationProfile(route));
});

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
        map.getCanvas().style.cursor = _selectedDrawnRoute() ? 'crosshair' : '';
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
    const dr = _selectedDrawnRoute();
    if (dr) dr.routeId = null;
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

  // Start pin — appears immediately on first waypoint
  if (n >= 1) {
    const s = state.waypoints[0];
    drawnStartMarker.setLngLat([s[1], s[0]]).addTo(map);
    elDrawStartCoord.textContent = `${s[0].toFixed(5)}, ${s[1].toFixed(5)}`;
  } else {
    drawnStartMarker.remove();
    elDrawStartCoord.textContent = '—';
  }

  // End pin — appears after second waypoint
  if (n >= 2) {
    const e = state.waypoints[n - 1];
    drawnEndMarker.setLngLat([e[1], e[0]]).addTo(map);
    elDrawEndCoord.textContent = `${e[0].toFixed(5)}, ${e[1].toFixed(5)}`;
  } else {
    drawnEndMarker.remove();
    elDrawEndCoord.textContent = '—';
  }

  elDrawEndpoints.classList.toggle('hidden', n === 0);

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
  elBtnReverseDraw.disabled = state.segmentCoords.length === 0;
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

    const dr = _selectedDrawnRoute();
    if (dr) {
      dr.routeId    = data.route_id;
      dr.bounds     = data.bounds;
      dr.startCoord = state.waypoints[0];
      dr.endCoord   = state.waypoints[state.waypoints.length - 1];
    }
    state.routeId     = data.route_id;
    state.routeSource = 'drawn';
    state.startCoord  = state.waypoints[0];
    state.endCoord    = state.waypoints[state.waypoints.length - 1];
    runPreview();

    const dr2 = _selectedDrawnRoute();
    if (dr2) fetchDrawnRouteElevation(dr2, coords);
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
document.getElementById('lyr-contours').addEventListener('change', (e) => {
  const vis = e.target.checked ? 'visible' : 'none';
  ['contours-layer', 'contours-major-layer', 'contours-label-layer'].forEach(id => {
    if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis);
  });
});
document.getElementById('lyr-hillshade').addEventListener('change', (e) => {
  if (map.getLayer('terrain-hillshade'))
    map.setLayoutProperty('terrain-hillshade', 'visibility', e.target.checked ? 'visible' : 'none');
});
document.getElementById('map-3d').addEventListener('change', (e) => {
  if (e.target.checked) {
    map.dragRotate.enable();
  } else {
    map.dragRotate.disable();
    map.easeTo({ pitch: 0, bearing: 0, duration: 300 });
  }
});

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
  const raw = (state.selectedIdx !== null ? state.routes[state.selectedIdx]?.filename : null) || 'trail_map';
  return raw.replace(/[^\w\s\-]/g, '').replace(/\s+/g, ' ').trim() || 'trail_map';
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
elBtnReverseDraw.addEventListener('click', reverseRoute);

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
  drawnStartMarker.remove();
  drawnEndMarker.remove();
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

// Render route list on load so the "+" button is visible immediately
renderRouteList();

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

// ── Help tooltip ───────────────────────────────────────────────────────────
const elHelpTooltip = document.createElement('div');
elHelpTooltip.id = 'help-tooltip';
document.body.appendChild(elHelpTooltip);

document.addEventListener('mouseover', (e) => {
  const tip = e.target.closest('.help-tip');
  if (!tip) return;
  elHelpTooltip.textContent = tip.dataset.tooltip || '';
  elHelpTooltip.classList.add('visible');

  const r  = tip.getBoundingClientRect();
  const tw = 210;
  const margin = 8;
  let left = r.right + margin;
  if (left + tw > window.innerWidth - margin) left = r.left - tw - margin;
  left = Math.max(margin, left);
  let top = r.top + r.height / 2 - 26;
  top = Math.max(margin, Math.min(top, window.innerHeight - 120));
  elHelpTooltip.style.left = left + 'px';
  elHelpTooltip.style.top  = top + 'px';
});

document.addEventListener('mouseout', (e) => {
  if (e.target.closest('.help-tip')) elHelpTooltip.classList.remove('visible');
});

// ── Right-click elevation probe ────────────────────────────────────────────
const elElevProbe = document.getElementById('elev-probe');
let _probingElev  = false;

map.getCanvas().addEventListener('contextmenu', (e) => e.preventDefault());

map.getCanvas().addEventListener('mousedown', (e) => {
  if (e.button !== 2) return;
  // Do NOT preventDefault — MapLibre's DragRotateHandler needs this for right-click pitch/rotate
  _probingElev = true;
  _updateElevProbe(e);
});

window.addEventListener('mousemove', (e) => {
  if (_probingElev) _updateElevProbe(e);
});

window.addEventListener('mouseup', (e) => {
  if (e.button !== 2 || !_probingElev) return;
  _probingElev = false;
  elElevProbe.classList.add('hidden');
});

function _updateElevProbe(e) {
  const canvas = map.getCanvas();
  const rect   = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
    elElevProbe.classList.add('hidden');
    return;
  }
  const lngLat = map.unproject([x, y]);
  const elevM  = map.queryTerrainElevation(lngLat, { exaggerated: false });
  if (elevM === null) return;
  const elevFt = Math.round(elevM * 3.28084);
  elElevProbe.innerHTML =
    `<span class="elev-probe-ft">${elevFt} ft</span>` +
    `<span class="elev-probe-m">${Math.round(elevM)} m</span>`;
  // Position tooltip: right of cursor, flip left if near right edge
  let left = e.clientX + 16;
  let top  = e.clientY - 14;
  if (left + 110 > window.innerWidth) left = e.clientX - 126;
  elElevProbe.style.left = left + 'px';
  elElevProbe.style.top  = top  + 'px';
  elElevProbe.classList.remove('hidden');
}
