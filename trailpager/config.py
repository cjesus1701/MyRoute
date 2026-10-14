from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RouteConfig(BaseModel):
    file: Path
    start: tuple[float, float]  # [lat, lon] WGS-84
    end: tuple[float, float]


class MapConfig(BaseModel):
    scale: int = Field(24000, gt=0)
    page_size: Literal["letter", "a4"] = "letter"
    orientation: Literal["portrait", "landscape"] = "landscape"
    overlap_m: float = Field(500.0, ge=0)
    margin_m: float = Field(200.0, ge=0)
    utm_zone: int = Field(17, ge=1, le=60)


class LayersConfig(BaseModel):
    topo_basemap: bool = True
    usfs_boundary: bool = True
    nps_boundary: bool = True
    mile_markers: bool = True
    utm_grid: bool = True
    elevation_profile: bool = False
    pois: bool = True  # shelters and water sources


class OutputConfig(BaseModel):
    path: Path = Path("output/map.pdf")


class Settings(BaseModel):
    route: RouteConfig
    map: MapConfig = MapConfig()
    layers: LayersConfig = LayersConfig()
    output: OutputConfig = OutputConfig()

    @model_validator(mode="after")
    def _validate_margin(self) -> "Settings":
        if self.map.margin_m >= self.map.overlap_m:
            raise ValueError("margin_m must be less than overlap_m")
        return self

    @property
    def page_size_inches(self) -> tuple[float, float]:
        sizes = {
            ("letter", "landscape"): (11.0, 8.5),
            ("letter", "portrait"): (8.5, 11.0),
            ("a4", "landscape"): (11.69, 8.27),
            ("a4", "portrait"): (8.27, 11.69),
        }
        return sizes[(self.map.page_size, self.map.orientation)]

    @property
    def page_ground_size_m(self) -> tuple[float, float]:
        """Page frame dimensions in ground meters at the configured scale."""
        w_in, h_in = self.page_size_inches
        factor = self.map.scale * 0.0254
        return w_in * factor, h_in * factor

    @property
    def epsg(self) -> int:
        return 32600 + self.map.utm_zone


def load_settings(path: Path) -> Settings:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return Settings.model_validate(data)
