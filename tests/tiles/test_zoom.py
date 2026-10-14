from trailpager.tiles.fetcher import zoom_for_scale


def test_zoom_24k_300dpi():
    # 1:24,000 at 300 DPI: pixel-perfect is 16, label-readable target is 14
    assert zoom_for_scale(24000) == 14


def test_zoom_50k_300dpi():
    assert zoom_for_scale(50000) == 13


def test_zoom_100k_300dpi():
    assert zoom_for_scale(100000) == 12


def test_zoom_clamped_low():
    # Very small-scale maps clamp to z10
    assert zoom_for_scale(2_000_000) == 10


def test_zoom_clamped_high():
    # Very large-scale maps clamp to z18
    assert zoom_for_scale(1_000) == 18
