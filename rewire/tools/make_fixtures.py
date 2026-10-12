# SPDX-License-Identifier: MIT
"""Build golden-case INPUTS for the three uwg transforms (expected outputs come from tools/freeze_goldens.py).

    ~/venvs/spine/bin/python rewire/tools/make_fixtures.py
Plain pandas/geopandas; does not import uwg.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

REPO = Path(__file__).resolve().parents[2]
RW = REPO / "rewire"
EPW = REPO / "resources" / "SGP_Singapore.486980_IWEC.epw"
INIT = REPO / "resources" / "initialize_singapore.uwg"
CRS = "EPSG:3414"
SV = "fixture-v1"
# Two synthetic 100 m x 100 m districts in SVY21 metres (near Tanjong Pagar), side by side.
REF_X0, DENSE_X0, Y0 = 29000.0, 29100.0, 28800.0


def load_adapter(transform_id: str):
    spec = importlib.util.spec_from_file_location(f"rw_{transform_id.replace('.', '_')}", RW / transform_id / "adapter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def init_params() -> dict:
    """bldHeight/bldDensity/verToHor/grasscover/treeCover as written in UWG's own Singapore .uwg file."""
    want = {"bldHeight": "bldheight", "bldDensity": "blddensity", "verToHor": "vertohor",
            "grasscover": "grasscover", "treeCover": "treecover"}
    out = {}
    for line in INIT.read_text().splitlines():
        m = re.match(r"^\s*([A-Za-z]+)\s*,\s*([-0-9.eE]+)", line)
        if m and m.group(1) in want:
            out[want[m.group(1)]] = float(m.group(2))
    assert set(out) == set(want.values()), out
    return out


def write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def epw_case() -> None:
    d = RW / "epw.weather_conform" / "golden" / "singapore_iwec" / "inputs" / "epw"
    d.mkdir(parents=True, exist_ok=True)
    link = d / EPW.name
    link.unlink(missing_ok=True)
    link.symlink_to(Path("../../../../../../resources") / EPW.name)  # reuse the bundled file, no copy


def morphology_case() -> pd.DataFrame:
    case = RW / "morphology.district" / "golden" / "singapore_reference"
    districts = gpd.GeoDataFrame({
        "district_id": ["D-SG-REF", "D-SG-DENSE"],
        "name": ["UWG Singapore reference block", "Dense high-rise block"],
        "geometry": [box(REF_X0, Y0, REF_X0 + 100, Y0 + 100), box(DENSE_X0, Y0, DENSE_X0 + 100, Y0 + 100)],
        "source_version": SV}, crs=CRS)
    b = []
    # D-SG-REF: 8 detached 25 x 25 m, 10 m buildings -> footprint 5000 m2, facade 8 * 100 m * 10 m = 8000 m2.
    for i, (dx, dy) in enumerate([(5, 5), (37.5, 5), (70, 5), (5, 37.5), (37.5, 37.5), (70, 37.5), (5, 70), (37.5, 70)]):
        b.append({"building_id": f"B-REF-{i + 1}", "district_id": "D-SG-REF",
                  "geometry": box(REF_X0 + dx, Y0 + dy, REF_X0 + dx + 25, Y0 + dy + 25), "height_m": 10.0, "storeys": 3})
    # D-SG-DENSE: 4 detached 40 x 40 m towers, two 30 m and two 45 m.
    for i, (dx, dy, h) in enumerate([(5, 5, 30.0), (55, 5, 30.0), (5, 55, 45.0), (55, 55, 45.0)]):
        b.append({"building_id": f"B-DENSE-{i + 1}", "district_id": "D-SG-DENSE",
                  "geometry": box(DENSE_X0 + dx, Y0 + dy, DENSE_X0 + dx + 40, Y0 + dy + 40), "height_m": h,
                  "storeys": int(h // 3)})
    buildings = gpd.GeoDataFrame(b, crs=CRS).assign(source_version=SV)
    lc = []
    for i, (dx, dy, tree, grass) in enumerate([(0, 0, 0.2, 0.1), (50, 0, 0.0, 0.1), (0, 50, 0.1, 0.05), (50, 50, 0.1, 0.15)]):
        lc.append({"cell_id": f"LC-REF-{i + 1}", "district_id": "D-SG-REF",
                   "geometry": box(REF_X0 + dx, Y0 + dy, REF_X0 + dx + 50, Y0 + dy + 50), "lcz": 3,
                   "tree_cover": tree, "grass_cover": grass})
    lc.append({"cell_id": "LC-DENSE-1", "district_id": "D-SG-DENSE",
               "geometry": box(DENSE_X0, Y0, DENSE_X0 + 100, Y0 + 100), "lcz": 1, "tree_cover": 0.05, "grass_cover": 0.05})
    land_cover = gpd.GeoDataFrame(lc, crs=CRS).assign(source_version=SV)
    for name, df in {"districts": districts, "buildings": buildings, "land_cover": land_cover}.items():
        write(df, case / "inputs" / f"{name}.parquet")

    ref = init_params()
    expected = pd.DataFrame([
        {"district_id": "D-SG-REF", "district_area_m2": 10000.0, "n_buildings": 8, **ref},
        {"district_id": "D-SG-DENSE", "district_area_m2": 10000.0, "n_buildings": 4,
         "bldheight": (30 * 1600 * 2 + 45 * 1600 * 2) / 6400, "blddensity": 6400 / 10000,
         "vertohor": 160 * (30 + 30 + 45 + 45) / 10000, "grasscover": 0.05, "treecover": 0.05},
    ])
    write(expected, case / "expected" / "district_morphology.parquet")
    return expected


def urban_heat_cases(morph: pd.DataFrame) -> None:
    conf = load_adapter("epw.weather_conform")
    out = conf.run({"epw": RW / "epw.weather_conform" / "golden" / "singapore_iwec" / "inputs" / "epw"}, {})
    weather = out["weather_hourly"]
    for case, rows in {"singapore_jan": morph, "matlab_reference": morph[morph["district_id"] == "D-SG-REF"]}.items():
        d = RW / "uwg.urban_heat" / "golden" / case
        write(weather, d / "inputs" / "weather_hourly.parquet")
        write(rows.reset_index(drop=True), d / "inputs" / "district_morphology.parquet")
        (d / "params.json").write_text(json.dumps({}) + "\n")


if __name__ == "__main__":
    epw_case()
    urban_heat_cases(morphology_case())
    print("fixture inputs written under", RW)
