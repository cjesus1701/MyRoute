# Trail Map PDF Generator: Product Spec (Draft 0.1)

Working title: **TrailPager**
Status: Starting document for planning and for the first build with Claude Code
Date: 2026-10-14

---

## 1. Purpose

Build a small custom app that takes a trail route with a start and an end point and produces a printable PDF map of that route. If the route is too long to read clearly on one page at a useful scale, the app splits it into multiple pages, numbered in order from the start of the route to the finish.

## 2. Background and motivating use case

The first user is a backpacker planning a 3-day hike on the Appalachian Trail (AT) in Virginia, from **Reids Gap** (near Wintergreen Resort; also spelled "Reeds Gap" on many maps and guidebooks) to **Rockfish Gap**.

- Estimated length: about 17 miles (about 4.8 miles from Reids Gap to the Blue Ridge Parkway mile 9.6 area, plus about 12 miles on to Rockfish Gap). These figures come from trail listings and should be checked against the real trail data.
- The route runs through George Washington National Forest. Shenandoah National Park begins at Rockfish Gap.
- The hiker carries a Magellan GPS Pioneer, which shows UTM or latitude/longitude coordinates and bearings to saved landmarks, but has no map display. A paper map is the primary navigation aid.
- Existing paper option: PATC Map 12 (Rockfish Gap to Tye River). The app is meant to complement it, not replace it, and PATC Map 12 serves as a comparison for checking results.

## 3. Goals

1. Produce a clear, printable PDF of a route from a chosen start point to a chosen end point.
2. Show the trail, the relevant public-land boundary (for example, national forest or national park), and topographic context.
3. Keep detail readable by fixing the map scale and splitting the route across pages when needed.
4. Order pages from start to finish and make the order obvious to the reader.
5. Help the hiker use a GPS handheld with the paper map by printing a coordinate grid and a waypoint table.

## 4. Non-goals (for the first version)

- A live tracking app. It does not follow a GPS position or give turn-by-turn navigation.
- A web service with user accounts. This is a local app that runs on the user's own computer, with no sign-in, no hosted server, and no user data stored online.
- Replacing official maps. The output is a planning aid and must say so on the PDF.
- Offline map tile caching for distribution to others.

## 5. Users and scenarios

- **Primary user:** an individual hiker preparing a trip who wants a custom printout.
- **Scenario A:** Enter "Reids Gap" as start and "Rockfish Gap" as end for the AT, get a multi-page PDF.
- **Scenario B:** Load a GPX file of any trail, choose start and end points on it, get a PDF.
- **Scenario C:** Adjust the scale (for example, more detail with more pages, or less detail with fewer pages) and regenerate.

## 6. Inputs

| Input | Description |
|---|---|
| Route line | A trail track as GPX or GeoJSON (the full trail or a longer section than needed) |
| Start point | Coordinates or a named place; snapped to the nearest point on the route line |
| End point | Same as start |
| Scale | Target map scale (for example 1:24,000 or 1:50,000) |
| Page size and orientation | Letter or A4; portrait or landscape |
| Overlap | Margin of repeated map between consecutive pages |
| Layers | Choices such as boundary layers, mile markers, grid on or off |

## 7. Outputs

A single PDF containing:

1. **Overview page.** The entire route on one map, with a rectangle for each detail page and its page number.
2. **Detail pages.** Numbered "Page N of M" in route order from start to finish. Each page shows:
   - Topographic background
   - The route, highlighted, with direction of travel and mile markers measured from the start
   - Public-land boundary lines (for example, national forest boundary), labeled
   - A coordinate grid (UTM) with the datum stated
   - Scale bar, north arrow, and a short note about which page comes before and after
3. **Waypoint table.** Names and coordinates of key points (start, end, junctions, campsites, water) in the format the user's GPS expects.
4. **Disclaimer.** The map is a planning aid, with data sources and dates listed, and a reminder to carry an official map and compass.

## 8. Functional requirements

1. **Load route.** Read a GPX or GeoJSON file and build a single continuous line.
2. **Trim to start and end.** Snap start and end points to the nearest points on the line and keep only the portion between them.
3. **Compute length and mile markers.** Measure distance along the trimmed line.
4. **Paginate.** Given scale and page size, divide the route into the smallest number of pages that:
   - keeps the route inside each page frame with a safe margin,
   - overlaps adjacent pages by the chosen margin,
   - orders pages from start to finish.
5. **Render each page** with the layers listed in section 7.
6. **Assemble the PDF** with the overview page first, then detail pages, then the waypoint table.
7. **Configuration.** Store settings (scale, paper size, layers) in a simple settings file so runs can be repeated.
8. **Clear errors.** Report missing data, start or end points that are far from the route, or data that can't be downloaded.

## 9. Pagination approach (core logic)

1. Convert the page size and scale to a ground distance (for example, a letter-size map frame at 1:24,000 covers a fixed number of meters).
2. Walk along the route from the start. Place the first page frame so the start sits near the frame's edge with the route heading into the page.
3. Extend the frame along the route until the next route point would fall outside the frame's safe margin. That point is the end of the page.
4. Begin the next page at (end of previous page minus overlap).
5. Repeat until the end point is reached.
6. For routes that turn sharply, allow frames to be oriented north-up but shifted to the best position along the route.

Open design choice: north-up pages only, or rotate pages to follow the trail direction. Start with north-up because it's simpler and matches the GPS and compass.

## 10. Data sources (to be verified before use)

The first task for the project is confirming that each source is available, current, and permitted for this use.

- **Trail line:** Appalachian Trail Conservancy public data, or OpenStreetMap. Compare both against PATC Map 12.
- **Topographic basemap:** USGS National Map / US Topo.
- **Boundaries:** US Forest Service data for George Washington National Forest; National Park Service data for Shenandoah National Park.
- **Reference for validation:** PATC Map 12 (scale 1:63,360, 100-foot contours, UTM grid, NAD 83 datum, as listed by the seller).

Each source's terms of use and any rate limits must be checked and respected. No scraping of services that forbid it.

## 11. Suggested technology

- **Language:** Python.
- **Geospatial:** geopandas, shapely, pyproj (for UTM and datum conversion), gpxpy for GPX files.
- **Rendering:** matplotlib or a map-drawing library that can output vector PDF.
- **PDF assembly:** the plotting library's multi-page PDF support, or reportlab.
- **Interface:** a local app that runs on the user's own computer. Start as a command-line tool with a settings file; a simple local window or a page served only on the user's own machine (not hosted online) can come later.
- **Testing:** pytest.

## 12. Development plan

**Milestone 0 - Data check.** Confirm sources, download the trail data for the Reids Gap to Rockfish Gap section, and compare its length to the roughly 17-mile estimate.

**Milestone 1 - One page.** Draw the full route on a single page with the basemap, boundary, mile markers, and scale bar. Check by eye against PATC Map 12.

**Milestone 2 - Trim and measure.** Start and end snapping, route length, mile markers.

**Milestone 3 - Pagination.** Implement the algorithm in section 9 with automated tests for page order, overlap, and full coverage of the route.

**Milestone 4 - Overview and tables.** Overview page with page footprints, waypoint table, disclaimer.

**Milestone 5 - Field test.** Print the PDF, take it on the planned overnight test, and compare it to the terrain and to Pioneer readouts. Record fixes.

**Milestone 6 - Extras.** Elevation profile, shelters and water sources, support for other trails.

## 13. Testing and validation

- **Known-distance test:** compute the length of the trimmed route and compare to published mileage.
- **Coverage test:** every point of the route must appear on at least one page, inside the frame's safe margin.
- **Order test:** page numbers increase with distance from the start.
- **Overlap test:** consecutive pages share the chosen overlap.
- **Coordinate test:** the grid coordinates printed on a page for a known point (for example, a trailhead) match the same point's coordinates on a handheld GPS, using the same datum.
- **Visual check:** compare against PATC Map 12 for the same area.

## 14. Risks and open questions

- **Data accuracy and currency:** trail relocations and boundary changes can make data out of date. Show the data date on the PDF.
- **Source terms:** some tile services restrict bulk downloading or printing.
- **Datum mismatch:** the GPS datum and the map datum must match. The Pioneer supports changing both; the PDF should print the datum it uses.
- **Print scale:** a PDF printed with "fit to page" will not match its stated scale. The PDF should state to print at 100 percent.
- **Open questions:**
  - Which exact start and end points should be used for Reids Gap and Rockfish Gap (parking lot versus trail crossing)?
  - Should pages be north-up only?
  - Which paper size will the user print on?
  - Should the app also support out-and-back and loop routes?

## 15. Success criteria for version 1

- Generates a multi-page PDF for the Reids Gap to Rockfish Gap route with no manual drawing.
- Pages are in order from start to finish and clearly numbered.
- Distances and positions agree with PATC Map 12 within reasonable tolerance, and any differences are understood.
- The user can print it and use it on the shakedown hike alongside the Pioneer.

## 16. Disclaimer to include on the product and output

This product is a planning aid. It does not replace official maps, a compass, or good judgment. Verify trail conditions, closures, and regulations with the managing agency before a trip.
