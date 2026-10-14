from trailpager.tiles.fetcher import zoom_for_scale


def test_zoom_24k_300dpi():
    # 1:24,000 at 300 DPI should hit the USGS 7.5-min quad level (z16)
    assert zoom_for_scale(24000) == 16


def test_zoom_50k_300dpi():
    assert zoom_for_scale(50000) == 15


def test_zoom_100k_300dpi():
    assert zoom_for_scale(100000) == 14


def test_zoom_clamped_low():
    # Very small-scale maps (>~1:1.8M) would compute below z10 — clamp to 10
    assert zoom_for_scale(2_000_000) == 10


def test_zoom_clamped_high():
    # Very large-scale maps should not exceed z18
    assert zoom_for_scale(1_000) == 18
