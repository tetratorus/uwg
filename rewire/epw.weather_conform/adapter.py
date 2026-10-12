# SPDX-License-Identifier: MIT
"""epw.weather_conform: EnergyPlus Weather (EPW) files in bronze -> silver weather_hourly + id_bridge.

Plain CSV parsing; this module does not import the GPL `uwg` package, so the spine can load it in-process.
EPW column layout: https://bigladdersoftware.com/epx/docs/8-2/auxiliary-programs/epw-csv-format-inout.html

Timestamps: EPW hour h (1-24) is the hour ending at h, local standard time (header field 9 = UTC offset).
We store the end of the interval in UTC, e.g. 1989-01-01 hour 1 at UTC+8 -> 1988-12-31T17:00Z.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

import pandas as pd

# EPW data columns (0-based) that land in silver.
_COLS = {
    "dry_bulb_c": 6,
    "dew_point_c": 7,
    "rh_pct": 8,
    "pressure_pa": 9,
    "horizontal_ir_wm2": 12,
    "ghi_wm2": 13,
    "dni_wm2": 14,
    "dhi_wm2": 15,
    "wind_dir_deg": 20,
    "wind_speed_ms": 21,
}
# EPW "missing" sentinels (EnergyPlus Auxiliary Programs, EPW CSV format).
_MISSING = {"dry_bulb_c": 99.9, "dew_point_c": 99.9, "rh_pct": 999.0, "pressure_pa": 999999.0,
            "horizontal_ir_wm2": 9999.0, "ghi_wm2": 9999.0, "dni_wm2": 9999.0, "dhi_wm2": 9999.0,
            "wind_dir_deg": 999.0, "wind_speed_ms": 999.0}


def station_hub_id(wmo: str) -> str:
    return f"wmo-{wmo}"


def read_header(rows: list[list[str]]) -> dict:
    loc = rows[0]
    if loc[0].strip().upper() != "LOCATION":
        raise ValueError("not an EPW file: first line must start with LOCATION")
    ground = rows[3]
    if ground[0].strip().upper() != "GROUND TEMPERATURES":
        raise ValueError("EPW line 4 must be GROUND TEMPERATURES")
    n = int(ground[1])
    depths = []
    for i in range(n):
        base = 2 + 16 * i
        depths.append({"depth_m": float(ground[base]),
                       "conductivity": ground[base + 1].strip(),
                       "density": ground[base + 2].strip(),
                       "specific_heat": ground[base + 3].strip(),
                       "monthly_c": [float(v) for v in ground[base + 4: base + 16]]})
    return {"city": loc[1].strip(), "region": loc[2].strip(), "country": loc[3].strip(),
            "data_source": loc[4].strip(), "wmo": loc[5].strip(), "latitude_deg": float(loc[6]),
            "longitude_deg": float(loc[7]), "utc_offset_h": float(loc[8]), "elevation_m": float(loc[9]),
            "ground_temperatures": depths}


def ground_temps_json(depths: list[dict]) -> str:
    """The part of EPW GROUND TEMPERATURES that UWG reads (depth + 12 monthly values), as compact JSON."""
    return json.dumps([{"depth_m": round(float(d["depth_m"]), 6), "monthly_c": [round(float(v), 6) for v in d["monthly_c"]]}
                       for d in depths], separators=(",", ":"))


def read_epw(path: Path, source_version: str) -> tuple[pd.DataFrame, dict]:
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    hdr = read_header(rows[:8])
    data = rows[8:]
    tz = dt.timedelta(hours=hdr["utc_offset_h"])
    ts = [dt.datetime(int(r[0]), int(r[1]), int(r[2])) + dt.timedelta(hours=int(r[3])) - tz for r in data]
    df = pd.DataFrame({"station_id": station_hub_id(hdr["wmo"]),
                       "timestamp": pd.to_datetime(ts).tz_localize("UTC")})
    for name, idx in _COLS.items():
        s = pd.to_numeric(pd.Series([r[idx] for r in data]), errors="coerce").astype(float)
        df[name] = s.mask(s >= _MISSING[name])
    df["latitude_deg"] = hdr["latitude_deg"]
    df["longitude_deg"] = hdr["longitude_deg"]
    df["utc_offset_h"] = hdr["utc_offset_h"]
    df["elevation_m"] = hdr["elevation_m"]
    df["ground_temps_json"] = ground_temps_json(hdr["ground_temperatures"])
    df["source_version"] = source_version
    return df, hdr


def run(inputs, params):
    bronze = Path(inputs["epw"])
    version = bronze.name
    files = sorted(p for p in bronze.rglob("*") if p.suffix.lower() == ".epw")
    if not files:
        raise FileNotFoundError(f"no .epw files in {bronze}")
    frames, bridge = [], []
    for p in files:
        df, hdr = read_epw(p, version)
        frames.append(df)
        hub = station_hub_id(hdr["wmo"])
        bridge += [
            {"source": "wmo", "source_id": hdr["wmo"], "hub": "station", "hub_id": hub,
             "match_method": "exact", "confidence": 1.0, "source_version": version},
            {"source": "epw", "source_id": p.stem, "hub": "station", "hub_id": hub,
             "match_method": "exact", "confidence": 1.0, "source_version": version},
        ]
    weather = pd.concat(frames, ignore_index=True)
    id_bridge = pd.DataFrame(bridge).drop_duplicates(["source", "source_id"]).reset_index(drop=True)
    return {"weather_hourly": weather, "id_bridge": id_bridge}
