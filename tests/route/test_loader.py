import json

import pytest
from shapely.geometry import LineString

GPX_CONTENT = """\
<?xml version="1.0"?>
<gpx version="1.1" creator="test">
  <trk>
    <trkseg>
      <trkpt lat="37.90" lon="-79.00"/>
      <trkpt lat="37.91" lon="-79.01"/>
      <trkpt lat="37.92" lon="-79.02"/>
    </trkseg>
  </trk>
</gpx>
"""


def test_load_gpx_returns_linestring(tmp_path):
    from trailpager.route.loader import load_route

    f = tmp_path / "test.gpx"
    f.write_text(GPX_CONTENT)
    result = load_route(f)
    assert isinstance(result.line, LineString)
    assert result.crs == "EPSG:4326"


def test_load_gpx_correct_point_count(tmp_path):
    from trailpager.route.loader import load_route

    f = tmp_path / "test.gpx"
    f.write_text(GPX_CONTENT)
    result = load_route(f)
    assert len(result.line.coords) == 3


def test_load_geojson_returns_linestring(tmp_path):
    from trailpager.route.loader import load_route

    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[-79.0, 37.9], [-79.01, 37.91], [-79.02, 37.92]],
            },
            "properties": {},
        }],
    }
    f = tmp_path / "test.geojson"
    f.write_text(json.dumps(geojson))
    result = load_route(f)
    assert isinstance(result.line, LineString)


def test_load_unsupported_extension_raises(tmp_path):
    from trailpager.route.loader import load_route

    f = tmp_path / "test.kml"
    f.write_text("<kml/>")
    with pytest.raises(ValueError, match="Unsupported file type"):
        load_route(f)
