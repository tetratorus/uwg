# SPDX-License-Identifier: MIT
"""morphology.district: silver buildings + land_cover + districts -> gold district_morphology.

Computes the five urban-canopy inputs UWG reads from a .uwg parameter file, one row per spine district:

  bldheight   footprint-area-weighted mean building height [m]      (UWG bldHeight)
  blddensity  building footprint area / district land area [0-1]    (UWG bldDensity)
  vertohor    facade (wall) area / district land area [-]           (UWG verToHor)
  grasscover  grass-covered area / district land area [0-1]         (UWG grasscover)
  treecover   tree-covered area / district land area [0-1]          (UWG treeCover)

Geometry is EPSG:3414 (SVY21, metres), so areas and lengths are planar m2 / m.
Plain geopandas; nothing here imports the GPL uwg package.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

CRS = "EPSG:3414"


def _gdf(df: pd.DataFrame) -> gpd.GeoDataFrame:
    g = df if isinstance(df, gpd.GeoDataFrame) else gpd.GeoDataFrame(df, geometry="geometry")
    if g.crs is None:
        g = g.set_crs(CRS)
    return g.to_crs(CRS)


def building_heights(b: pd.DataFrame, storey_height_m: float) -> pd.Series:
    h = pd.to_numeric(b.get("height_m"), errors="coerce") if "height_m" in b else pd.Series(np.nan, index=b.index)
    if "storeys" in b:
        h = h.fillna(pd.to_numeric(b["storeys"], errors="coerce") * storey_height_m)
    return h


def run(inputs, params):
    storey_h = float(params.get("storey_height_m", 3.05))
    districts = _gdf(inputs["districts"])[["district_id", "geometry"]]
    b = _gdf(inputs["buildings"]).copy()
    lc = _gdf(inputs["land_cover"]).copy()

    b["h"] = building_heights(b, storey_h)
    b = b[b["h"].notna() & (b["h"] > 0) & ~b.geometry.is_empty]
    b["fp"] = b.geometry.area
    b["wall"] = b.geometry.exterior.length * b["h"] if (b.geom_type == "Polygon").all() else \
        b.geometry.boundary.length * b["h"]

    rows = []
    for d in districts.itertuples():
        area = d.geometry.area
        bd = b[b["district_id"] == d.district_id]
        fp = float(bd["fp"].sum())
        cells = lc[lc.intersects(d.geometry)]
        inter = cells.geometry.intersection(d.geometry).area
        tree = float((inter * cells["tree_cover"].fillna(0.0)).sum())
        grass = float((inter * cells["grass_cover"].fillna(0.0)).sum())
        rows.append({
            "district_id": d.district_id,
            "district_area_m2": area,
            "n_buildings": int(len(bd)),
            "bldheight": float((bd["h"] * bd["fp"]).sum() / fp) if fp > 0 else 0.0,
            "blddensity": fp / area,
            "vertohor": float(bd["wall"].sum()) / area,
            "grasscover": grass / area,
            "treecover": tree / area,
        })
    out = pd.DataFrame(rows, columns=["district_id", "district_area_m2", "n_buildings", "bldheight",
                                      "blddensity", "vertohor", "grasscover", "treecover"])
    bad = out[out["blddensity"] + out["grasscover"] + out["treecover"] > 1 + 1e-9]
    if len(bad):
        raise ValueError(f"building + grass + tree cover exceeds district area for {bad['district_id'].tolist()}")
    return {"district_morphology": out}
