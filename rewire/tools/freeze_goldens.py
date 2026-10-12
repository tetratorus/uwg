# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) the uwg contributors. Imports the GPL uwg package: run it ONLY inside the GPL runtime image.
"""Freeze golden EXPECTED outputs from the unmodified upstream UWG code (inputs: tools/make_fixtures.py).

    docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/work" tetratorus/uwg-urban-heat:0.1.0 \
        python /opt/rewire/tools/freeze_goldens.py /work

epw.weather_conform  expected: values read by uwg.weather.Weather and UWG._read_epw from the original IWEC EPW.
uwg.urban_heat       singapore_jan: UWG.from_param_file(resources/initialize_singapore.uwg, original EPW) per
                     district (morphology set as UWG attributes); NOT via the spine adapter or rebuilt EPW.
                     matlab_reference: upstream MATLAB output tests/matlab_ref/.../SGP_..._UWG_Matlab.epw.
"""
import csv
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

from uwg import UWG
from uwg.weather import Weather

REPO = Path(sys.argv[1] if len(sys.argv) > 1 else "/work")
RW = REPO / "rewire"
EPW = REPO / "resources" / "SGP_Singapore.486980_IWEC.epw"
INIT = REPO / "resources" / "initialize_singapore.uwg"
MATLAB = REPO / "tests" / "matlab_ref" / "matlab_output" / "SGP_Singapore.486980_IWEC_UWG_Matlab.epw"
ORDER = ("treecover", "grasscover", "bldheight", "vertohor", "treecover", "grasscover", "blddensity")


def rows(path):
    with open(path, newline="") as f:
        return list(csv.reader(f))


def utc(r, gmt):
    return dt.datetime(int(r[0]), int(r[1]), int(r[2])) + dt.timedelta(hours=int(r[3]) - gmt)


def write(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    print("wrote", path.relative_to(REPO), len(df), "rows")


def freeze_epw():
    m = UWG(str(EPW))
    m._read_epw()
    data = rows(EPW)[8:]
    w = Weather(str(EPW), 8, 8 + len(data) - 1)
    wmo = m._header[0][5].strip()
    station = f"wmo-{wmo}"
    df = pd.DataFrame({
        "station_id": station,
        "timestamp": pd.to_datetime([utc(r, m.gmt) for r in data]).tz_localize("UTC"),
        "dry_bulb_c": [t - 273.15 for t in w.staTemp], "dew_point_c": w.staTdp, "rh_pct": w.staRhum,
        "pressure_pa": w.staPres, "horizontal_ir_wm2": w.staInfra, "ghi_wm2": w.staHor, "dni_wm2": w.staDir,
        "dhi_wm2": w.staDif, "wind_dir_deg": w.staUdir, "wind_speed_ms": w.staUmod,
        "latitude_deg": m.lat, "longitude_deg": m.lon, "utc_offset_h": m.gmt,
        "elevation_m": float(m._header[0][9]),
        "ground_temps_json": json.dumps([{"depth_m": round(m.depth_soil[i][0], 6),
                                          "monthly_c": [round(t - 273.15, 6) for t in m.Tsoil[i]]}
                                         for i in range(m.nSoil)], separators=(",", ":")),
        "source_version": "epw",
    })
    case = RW / "epw.weather_conform" / "golden" / "singapore_iwec" / "expected"
    write(df, case / "weather_hourly.parquet")
    bridge = pd.DataFrame([
        {"source": "wmo", "source_id": wmo, "hub": "station", "hub_id": station, "match_method": "exact",
         "confidence": 1.0, "source_version": "epw"},
        {"source": "epw", "source_id": EPW.stem, "hub": "station", "hub_id": station, "match_method": "exact",
         "confidence": 1.0, "source_version": "epw"}])
    write(bridge, case / "id_bridge.parquet")
    return station


def direct_run(morph_row, tmp):
    m = UWG.from_param_file(str(INIT), epw_path=str(EPW), new_epw_dir=tmp, new_epw_name="direct.epw")
    for i, k in enumerate(ORDER):  # zero the covers first so UWG's blddensity+covers<=1 assertion holds
        setattr(m, k, 0.0 if i < 2 else float(morph_row[k]))
    m.generate()
    m.simulate()
    return m


def freeze_urban_heat(station):
    data = rows(EPW)[8:]
    gmt = float(rows(EPW)[0][8])
    case = RW / "uwg.urban_heat" / "golden"
    morph = pd.read_parquet(case / "singapore_jan" / "inputs" / "district_morphology.parquet")
    frames, ref = [], None
    with tempfile.TemporaryDirectory() as tmp:
        for row in morph.sort_values("district_id").to_dict("records"):
            m = direct_run(row, tmp)
            h0 = m.simTime.timeInitial - 8
            sel = data[h0:h0 + len(m.UCMData)]
            df = pd.DataFrame({
                "district_id": row["district_id"], "station_id": station,
                "timestamp": pd.to_datetime([utc(r, gmt) for r in sel]).tz_localize("UTC"),
                "urban_air_temp_c": [u.canTemp - 273.15 for u in m.UCMData],
                "rural_air_temp_c": [float(r[6]) for r in sel],
                "urban_dew_point_c": [u.Tdp for u in m.UCMData],
                "urban_rh_pct": [u.canRHum for u in m.UCMData]})
            df["uhi_c"] = df["urban_air_temp_c"] - df["rural_air_temp_c"]
            frames.append(df)
            if row["district_id"] == "D-SG-REF":
                ref = (df, m.simTime.timeInitial, m.simTime.timeFinal)
    write(pd.concat(frames, ignore_index=True), case / "singapore_jan" / "expected" / "urban_heat_hourly.parquet")

    df, ti, tf = ref
    mw = Weather(str(MATLAB), ti, tf)
    mat = pd.DataFrame({"district_id": "D-SG-REF", "timestamp": df["timestamp"],
                        "urban_air_temp_c": [t - 273.15 for t in mw.staTemp], "urban_dew_point_c": mw.staTdp,
                        "urban_rh_pct": mw.staRhum})
    write(mat, case / "matlab_reference" / "expected" / "urban_heat_hourly.parquet")
    for c in ("urban_air_temp_c", "urban_dew_point_c", "urban_rh_pct"):
        d = (df[c] - mat[c]).abs()
        print(f"python-vs-MATLAB {c}: max |diff| {d.max():.4f}, mean {d.mean():.4f}, p99 {d.quantile(0.99):.4f}")


if __name__ == "__main__":
    freeze_urban_heat(freeze_epw())
