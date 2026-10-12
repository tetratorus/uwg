# SPDX-License-Identifier: MIT
"""uwg.urban_heat thin adapter: spine tables <-> UWG file formats. Pure pandas, MIT.

This module never imports the GPL `uwg` package. The GPL side (runtime/run_uwg.py, inside the
docker image) imports *this* module to:
  * rebuild a model-ready EPW from silver weather_hourly   (epw_from_weather)
  * map a gold district_morphology row onto UWG attributes  (morphology_overrides)
  * assemble the gold urban_heat_hourly table                 (to_gold)
"""
from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd

# EPW data-row positions read by uwg.weather.Weather / UWG.write_epw, and the EPW "missing" sentinel per field.
EPW_FIELDS = {
    "dry_bulb_c": (6, 99.9), "dew_point_c": (7, 99.9), "rh_pct": (8, 999.0), "pressure_pa": (9, 999999.0),
    "horizontal_ir_wm2": (12, 9999.0), "ghi_wm2": (13, 9999.0), "dni_wm2": (14, 9999.0), "dhi_wm2": (15, 9999.0),
    "wind_dir_deg": (20, 999.0), "wind_speed_ms": (21, 999.0),
}
# Fields UWG does not read; written as the EPW "missing" sentinel (index -> value).
_FILLER = {10: "9999", 11: "9999", 16: "999999", 17: "999999", 18: "999999", 19: "9999", 22: "99", 23: "99",
           24: "9999", 25: "99999", 26: "9", 27: "999999999", 28: "999", 29: ".999", 30: "999", 31: "99",
           32: "999", 33: "999", 34: "99"}
EPW_DATA_SOURCE = "?9?9?9?9E0?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9*9*9?9?9?9"
# Order matters: UWG asserts blddensity + grasscover + treecover <= 1 on every assignment.
MORPHOLOGY_ATTRS = ("bldheight", "vertohor", "treecover", "grasscover", "blddensity")


def _num(v: float, missing: float) -> str:
    return repr(float(missing if pd.isna(v) else v))


def _station_rows(weather: pd.DataFrame, station_id: str | None) -> tuple[str, pd.DataFrame]:
    stations = sorted(weather["station_id"].unique())
    if station_id is None:
        if len(stations) != 1:
            raise ValueError(f"weather_hourly has stations {stations}; set params.station_id")
        station_id = stations[0]
    w = weather[weather["station_id"] == station_id].copy()
    if w.empty:
        raise ValueError(f"no weather_hourly rows for station {station_id}")
    return station_id, w


def epw_from_weather(weather: pd.DataFrame, station_id: str | None = None) -> tuple[str, list, str]:
    """Return (epw_text, utc_timestamps_in_row_order, station_id) for one station's typical year (8760 rows)."""
    station_id, w = _station_rows(weather, station_id)
    meta = w.iloc[0]
    off = dt.timedelta(hours=float(meta["utc_offset_h"]))
    ts = pd.to_datetime(w["timestamp"], utc=True).dt.tz_localize(None)
    start = ts + off - dt.timedelta(hours=1)  # local standard time, start of the EPW hour
    w = w.assign(_utc=ts, _y=start.dt.year, _m=start.dt.month, _d=start.dt.day, _h=start.dt.hour + 1)
    w = w[~((w["_m"] == 2) & (w["_d"] == 29))].sort_values(["_m", "_d", "_h"]).reset_index(drop=True)
    if len(w) != 8760:
        raise ValueError(f"UWG needs a full 8760-hour year; station {station_id} has {len(w)} hours")

    ground = json.loads(meta["ground_temps_json"])
    gt = [str(len(ground))]
    for g in ground:
        gt += [repr(float(g["depth_m"])), "", "", ""] + [repr(float(v)) for v in g["monthly_c"]]
    header = [
        ["LOCATION", station_id, "-", "-", "sg-urban-spine silver.weather_hourly", station_id,
         repr(float(meta["latitude_deg"])), repr(float(meta["longitude_deg"])), repr(float(meta["utc_offset_h"])),
         repr(float(meta["elevation_m"]))],
        ["DESIGN CONDITIONS", "0"],
        ["TYPICAL/EXTREME PERIODS", "0"],
        ["GROUND TEMPERATURES", *gt],
        ["HOLIDAYS/DAYLIGHT SAVINGS", "No", "0", "0", "0"],
        ["COMMENTS 1", f"rebuilt from silver.weather_hourly (source_version {meta['source_version']})"],
        ["COMMENTS 2", ""],
        ["DATA PERIODS", "1", "1", "Data", "Sunday", " 1/ 1", "12/31"],
    ]
    lines = [",".join(h) for h in header]
    for rd in w.to_dict("records"):
        f = [""] * 35
        f[0], f[1], f[2], f[3], f[4], f[5] = str(rd["_y"]), str(rd["_m"]), str(rd["_d"]), str(rd["_h"]), "60", \
            EPW_DATA_SOURCE
        for col, (i, miss) in EPW_FIELDS.items():
            f[i] = _num(rd.get(col, np.nan), miss)
        for i, v in _FILLER.items():
            f[i] = v
        lines.append(",".join(f))
    return "\n".join(lines) + "\n", list(w["_utc"]), station_id


def rural_temperatures(weather: pd.DataFrame, station_id: str) -> pd.Series:
    w = weather[weather["station_id"] == station_id]
    return pd.Series(w["dry_bulb_c"].to_numpy(), index=pd.to_datetime(w["timestamp"], utc=True).dt.tz_localize(None))


def morphology_overrides(row: dict) -> list[tuple[str, float]]:
    """(UWG attribute, value) pairs in a safe assignment order."""
    for k in MORPHOLOGY_ATTRS:
        v = row.get(k)
        if v is None or pd.isna(v):
            raise ValueError(f"district {row.get('district_id')}: {k} is missing")
    if row["blddensity"] <= 0 or row["bldheight"] <= 0:
        raise ValueError(f"district {row['district_id']}: UWG needs blddensity > 0 and bldheight > 0")
    return [("treecover", 0.0), ("grasscover", 0.0)] + [(k, float(row[k])) for k in MORPHOLOGY_ATTRS]


def to_gold(district_id: str, station_id: str, timestamps: list, urban_t_c: list, urban_tdp_c: list,
            urban_rh_pct: list, rural_t_c: list) -> pd.DataFrame:
    df = pd.DataFrame({
        "district_id": district_id,
        "station_id": station_id,
        "timestamp": pd.to_datetime(pd.Series(timestamps)).dt.tz_localize("UTC") if
        pd.to_datetime(pd.Series(timestamps)).dt.tz is None else pd.to_datetime(pd.Series(timestamps)),
        "urban_air_temp_c": np.asarray(urban_t_c, dtype=float),
        "rural_air_temp_c": np.asarray(rural_t_c, dtype=float),
        "urban_dew_point_c": np.asarray(urban_tdp_c, dtype=float),
        "urban_rh_pct": np.asarray(urban_rh_pct, dtype=float),
    })
    df["uhi_c"] = df["urban_air_temp_c"] - df["rural_air_temp_c"]
    return df
