# SPDX-License-Identifier: MIT
"""Integration tests for rewire/ (run with the sg-urban-spine venv):  python -m pytest rewire/tests -q

Nothing here imports the GPL uwg package; the UWG run is exercised through the docker runtime only.
"""
from __future__ import annotations

import ast
import csv
import importlib.util
import shutil
import subprocess
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from spine.golden import run_golden
from spine.transform import load_descriptor

RW = Path(__file__).resolve().parents[1]
REPO = RW.parent
EPW = REPO / "resources" / "SGP_Singapore.486980_IWEC.epw"
IDS = ["epw.weather_conform", "morphology.district", "uwg.urban_heat"]
IMAGE = "tetratorus/uwg-urban-heat:0.1.0"
MIT_FILES = [RW / t / "adapter.py" for t in IDS] + [RW / "tools" / "make_fixtures.py", Path(__file__)]


def _adapter(tid):
    spec = importlib.util.spec_from_file_location(f"t_{tid.replace('.', '_')}", RW / tid / "adapter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _image_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0


@pytest.mark.parametrize("path", MIT_FILES, ids=lambda p: str(p.relative_to(RW)))
def test_mit_code_never_imports_uwg(path):
    tree = ast.parse(path.read_text())
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "uwg" not in mods
    assert "SPDX-License-Identifier: MIT" in path.read_text().splitlines()[0]


@pytest.mark.parametrize("tid", IDS)
def test_descriptor_validates(tid):
    d = load_descriptor(RW / tid)
    assert d.id == tid
    assert d.data["upstream"]["license"] and d.data["upstream"]["commercial_use"]
    assert d.data["readiness"]["evidence"]


@pytest.mark.parametrize("tid", ["epw.weather_conform", "morphology.district"])
def test_golden_python_runtimes(tid):
    res = run_golden(load_descriptor(RW / tid))
    assert res and all(r.passed for r in res), [r.messages for r in res]


@pytest.mark.skipif(not _image_available(), reason=f"docker image {IMAGE} not built")
def test_golden_uwg_docker_runtime():
    res = run_golden(load_descriptor(RW / "uwg.urban_heat"))
    assert {r.case for r in res} == {"singapore_jan", "matlab_reference"}
    assert all(r.passed for r in res), [r.messages for r in res]


def test_epw_timestamps_are_utc_end_of_hour():
    w = _adapter("epw.weather_conform").read_epw(EPW, "v1")[0]
    assert len(w) == 8760 and str(w["timestamp"].dt.tz) == "UTC"
    with open(EPW, newline="") as f:
        first = list(csv.reader(f))[8]
    # Jan 1, hour 1 local (UTC+8) ends at 01:00 SGT = 17:00 UTC on Dec 31 of the previous year
    assert w["timestamp"].iloc[0] == pd.Timestamp(int(first[0]) - 1, 12, 31, 17, tz="UTC")


def test_epw_id_bridge_maps_onto_station_hub(tmp_path):
    d = tmp_path / "epw" / "v1"
    d.mkdir(parents=True)
    shutil.copy2(EPW, d / EPW.name)
    out = _adapter("epw.weather_conform").run({"epw": d}, {})
    br = out["id_bridge"].set_index("source")
    assert set(out["weather_hourly"]["station_id"]) == {"wmo-486980"}
    assert br.loc["wmo", "source_id"] == "486980" and br.loc["epw", "source_id"] == EPW.stem
    assert set(br["hub_id"]) == {"wmo-486980"} and set(br["hub"]) == {"station"}
    assert set(out["weather_hourly"]["source_version"]) == {"v1"}


def test_epw_rebuild_round_trips_every_field_uwg_reads():
    w = _adapter("epw.weather_conform").read_epw(EPW, "v1")[0]
    text, stamps, station = _adapter("uwg.urban_heat").epw_from_weather(w)
    with open(EPW, newline="") as f:
        orig = list(csv.reader(f))
    new = list(csv.reader(text.splitlines()))
    assert station == "wmo-486980" and len(new) == len(orig) == 8768 and len(stamps) == 8760
    assert [float(v) for v in new[0][6:10]] == [float(v) for v in orig[0][6:10]]  # lat, lon, gmt, elevation
    n = int(orig[3][1])
    for i in range(n):  # ground temperature depth + 12 monthly values (what UWG._read_epw uses)
        idx = [2 + 16 * i] + list(range(6 + 16 * i, 18 + 16 * i))
        assert [float(new[3][j]) for j in idx] == [float(orig[3][j]) for j in idx]
    for a, b in zip(new[8:], orig[8:]):
        assert [int(v) for v in a[1:4]] == [int(v) for v in b[1:4]]
        assert [float(a[j]) for j in (6, 7, 8, 9, 12, 13, 14, 15, 20, 21)] == \
               [float(b[j]) for j in (6, 7, 8, 9, 12, 13, 14, 15, 20, 21)]


def test_morphology_storey_fallback_and_partial_cells():
    crs = "EPSG:3414"
    districts = gpd.GeoDataFrame({"district_id": ["D1"], "geometry": [box(0, 0, 100, 100)]}, crs=crs)
    buildings = gpd.GeoDataFrame({"building_id": ["b1", "b2"], "district_id": ["D1", "D1"],
                                  "geometry": [box(0, 0, 10, 10), box(50, 50, 60, 70)],
                                  "height_m": [None, 20.0], "storeys": [4, None]}, crs=crs)
    land = gpd.GeoDataFrame({"cell_id": ["c1"], "geometry": [box(50, 0, 150, 100)],  # half outside D1
                             "tree_cover": [0.4], "grass_cover": [0.2]}, crs=crs)
    out = _adapter("morphology.district").run(
        {"districts": districts, "buildings": buildings, "land_cover": land}, {"storey_height_m": 3.0}
    )["district_morphology"].iloc[0]
    assert out["bldheight"] == pytest.approx((12 * 100 + 20 * 200) / 300)
    assert out["blddensity"] == pytest.approx(300 / 10000)
    assert out["vertohor"] == pytest.approx((40 * 12 + 60 * 20) / 10000)
    assert out["treecover"] == pytest.approx(0.4 * 5000 / 10000)
    assert out["grasscover"] == pytest.approx(0.2 * 5000 / 10000)


def test_morphology_overrides_keep_uwg_cover_invariant():
    order = _adapter("uwg.urban_heat").morphology_overrides(
        {"district_id": "D", "bldheight": 30, "blddensity": 0.7, "vertohor": 2, "grasscover": 0.1, "treecover": 0.1})
    # covers are zeroed before density rises, and density is set last, so UWG's sum<=1 assertion never trips
    assert order[:2] == [("treecover", 0.0), ("grasscover", 0.0)] and order[-1] == ("blddensity", 0.7)
