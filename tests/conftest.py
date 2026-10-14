import matplotlib
matplotlib.use("Agg")  # must be before any render imports

import shapely
import pytest
from pyproj import Transformer
from shapely.geometry import LineString


@pytest.fixture
def straight_line_wgs84():
    return LineString([(-79.0, 37.9), (-79.0, 37.99)])


@pytest.fixture
def straight_line_utm():
    t = Transformer.from_crs("EPSG:4326", "EPSG:32617", always_xy=True)
    line = LineString([(-79.0, 37.9), (-79.0, 37.99)])
    return shapely.transform(line, t.transform, interleaved=False)


@pytest.fixture
def z_shape_utm():
    return LineString([
        (700_000, 4_200_000),
        (710_000, 4_200_000),
        (700_000, 4_210_000),
        (710_000, 4_210_000),
    ])
