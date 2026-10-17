# MyRoute

MyRoute turns a hiking route into a printable, multi-page PDF trail map. Load a GPX/GeoJSON
track or draw a route on the map, choose a start and end point, and MyRoute splits the route
into overlapping map pages at a fixed print scale.

Each PDF contains:

- **Overview page:** the whole route on one page, with a UTM grid.
- **Detail pages:** topo basemap, the route, mile markers, UTM grid, USFS/NPS boundaries,
  shelters and water sources, and prev/next page hints.
- **Waypoint table:** mileage to each shelter, water source and endpoint.
- **Elevation profile:** the elevation of the whole route, with points of interest marked.
- **Disclaimer page:** where the data came from and the date it was fetched.

---

## Local setup

### Requirements

- Python **3.11 or newer** (`python3 --version`)
- Git
- An internet connection. Map tiles, elevation, routing, and shelter/water data are
  downloaded while you use the tool.

On Debian/Ubuntu you may also need the venv package: `sudo apt install python3-venv`.

### Install

```bash
git clone git@github.com:cjesus1701/MyRoute.git   # or https://github.com/cjesus1701/MyRoute.git
cd MyRoute

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install --upgrade pip
pip install .                      # add -e ".[dev]" instead if you plan to change the code
```

### Start the web interface

```bash
trailpager serve
```

This starts the server at <http://127.0.0.1:8000> and opens your browser. Useful options:

```bash
trailpager serve --port 8080       # use a different port
trailpager serve --no-open         # don't open a browser automatically
```

Press **Ctrl+C** to stop. The server listens on your own machine only (`127.0.0.1`) and has
no login. Don't change `--host` to expose it on a network.

### Update to the latest version

```bash
cd MyRoute
git pull
source .venv/bin/activate
pip install .
```

---

## Using the web interface

The sidebar on the left holds the workflow, top to bottom. The map is on the right.

### 1. Add a route

You can have up to **5 routes** loaded at once. Each one gets its own color.

- **Upload:** drag `.gpx`, `.geojson` or `.json` files onto the drop zone, or click
  **browse**.
- **Draw:** click the **+** tile in the route list to start a new drawn route (see
  [Drawing a route](#drawing-a-route)).

In the route list you can:

- click a route to select it (the PDF is made from the selected route),
- click its color swatch to change the color,
- click the edit icon to rename it (press Enter to save, Esc to cancel). The name is also used
  for the downloaded file,
- click the remove icon to delete it.

### 2. Set the start and end (uploaded routes)

When an uploaded route is selected, the **Start & end** panel appears. The PDF covers only the
part of the route between these two points.

- Type coordinates as `lat, lon` (for example `37.9013, -78.9852`), **or**
- click **⊕** next to Start or End, then click the map. Click **Cancel** on the banner to stop
  picking.
- Click **⇄** to reverse the direction of travel. This swaps start and end, so mileage counts
  the other way.
- **↓ GPX** / **↓ GeoJSON** download the route.

Points snap to the closest spot on the track, so they don't need to sit exactly on it.

### Drawing a route

With a drawn route selected, the **Route points** panel appears.

1. Pick a mode:
   - **Routed:** each click is joined to the previous one along roads and trails
     (Valhalla, with OSRM as a fallback).
   - **Freehand:** straight lines between clicks, for tracing a trail by hand.
2. Click the map to place waypoints. The first waypoint is the start and the last is the end.
3. Use **Undo** (Ctrl+Z) and **Redo** (Ctrl+Y or Ctrl+Shift+Z) to fix mistakes, and
   **⇄ Reverse route** to flip the direction.

If routing can't find a path between two points, that segment is drawn as an **orange dashed
straight line**. Add more waypoints nearby or switch that part to Freehand.

### 3. Check the page preview

Whenever the route, endpoints or settings change, MyRoute outlines each PDF page on the map
and shows the page count and mileage under the route panel. Any warnings show up here too.

### 4. Review elevation

The elevation panel at the bottom of the map shows the profile of the selected route, with
total distance, gain and loss. It also shows:

- a moving dot on the route that follows your mouse as you move over the profile,
- an **estimated hiking time** (Naismith's rule: 3 mph plus 1 hour per 2,000 ft of climb),
- an **estimated water need**, which goes up with steepness.

Treat the time and water figures as rough planning numbers, not advice. Close the panel with
**✕** and reopen it from the tab at the bottom of the map.

### 5. Adjust settings and layers (optional)

Click the settings icon in the sidebar header.

**Map settings**

| Setting   | Options / default | What it does |
|-----------|-------------------|--------------|
| Scale     | 1:24,000 (default), 1:50,000, 1:100,000 | Ground covered per page. 1:24,000 matches USGS topo maps and shows the most detail. |
| Paper     | Letter or A4, landscape or portrait | Size and orientation of the PDF pages. |
| Overlap   | 500 m (min 250) | Ground each page shares with the next, so you can orient yourself when you switch pages. |
| UTM zone  | 17 | Zone used for the UTM grid. Most of the eastern US is in zones 17–18. |
| 3D terrain | off | Tilts the on-screen map into 3D. Does not affect the PDF. |

**Layers**

| Layer | In PDF | On screen |
|-------|:------:|:---------:|
| Topo basemap | ✓ | ✓ |
| USFS boundary | ✓ | ✓ |
| NPS boundary | ✓ | ✓ |
| Mile markers | ✓ | ✓ |
| UTM grid | ✓ | ✓ |
| Elevation profile | ✓ | |
| Shelters & water (from OpenStreetMap) | ✓ | ✓ |
| Contour lines | | ✓ |
| Terrain shading | | ✓ |
| Black & white | ✓ | |

Turn on **Black & white** if you'll print on a monochrome printer.

### 6. Generate the PDF

Click **Generate PDF**. Long routes can take a minute or more, since tiles and data are
downloaded for every page. When it's done, the PDF downloads automatically, named after the
selected route.

Print at **100% / actual size** (not "fit to page") so the map scale stays correct.

---

## Command-line mode (optional)

You can also make a PDF without the browser, from a settings file.

```bash
cp settings.example.toml settings.toml
# edit settings.toml: route file, start/end [lat, lon], scale, layers, output path
trailpager generate                   # uses ./settings.toml
trailpager generate -c other.toml     # use a different settings file
trailpager generate --dry-run         # print the settings without rendering
```

The main sections of `settings.toml`:

```toml
[route]
file  = "data/my_route.gpx"
start = [37.9013, -78.9852]   # [lat, lon]
end   = [38.0310, -78.8580]

[map]
scale = 24000
page_size = "letter"          # "letter" | "a4"
orientation = "landscape"     # "portrait" | "landscape"
overlap_m = 500
margin_m  = 200               # must be less than overlap_m
utm_zone  = 17

[layers]
elevation_profile = true      # off by default in CLI mode
pois = true

[output]
path = "output/my_route.pdf"
```

Downloaded tiles are cached in `.tile_cache/` next to the settings file, so later runs over the
same area are faster.

---

## Troubleshooting

- **`trailpager: command not found`:** activate the virtual environment first
  (`source .venv/bin/activate`).
- **Port already in use:** run `trailpager serve --port 8001`.
- **Routes disappear after a restart:** this is expected. Loaded routes are kept in memory
  only. Export a drawn route with **↓ GPX** if you want to keep it.
- **Missing shelters, boundaries or elevation:** these come from public services
  (OpenStreetMap Overpass, USFS, NPS, USGS). If a service is slow or down, the PDF is still
  made without that layer. Try again later.
- **Blank or missing basemap:** check your internet connection. Tiles come from USGS and
  OpenStreetMap.

## Development

```bash
pip install -e ".[dev]"
pytest                    # unit tests
pytest -m "not network"   # skip tests that need internet
ruff check .
```

## Data sources

USGS National Map (topo tiles, elevation), OpenStreetMap (tiles, shelters and water via
Overpass), USFS and NPS boundary services, OpenTopoData, and Valhalla/OSRM routing. Please
follow each service's usage policy, especially for heavy use.
