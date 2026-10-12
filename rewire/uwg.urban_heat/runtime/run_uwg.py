# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) the uwg contributors. Runs only inside the GPL runtime image (see ../Dockerfile).
"""Spine directory-contract runner for UWG:  run_uwg.py <inputs_dir> <params.json> <outputs_dir>

inputs/weather_hourly.parquet + inputs/district_morphology.parquet  ->  outputs/urban_heat_hourly.parquet
One unmodified UWG simulation per district: UWG.from_param_file(base .uwg) with the district's morphology.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adapter as A  # noqa: E402  (MIT mapping code; GPL code may import MIT code, never the reverse)
from uwg import UWG  # noqa: E402

DEFAULT_PARAM_FILE = os.environ.get("UWG_PARAM_FILE", "/opt/uwg/resources/initialize_singapore.uwg")


def simulate_district(epw_path, row, params, workdir):
    m = UWG.from_param_file(params.get("param_file") or DEFAULT_PARAM_FILE, epw_path=str(epw_path),
                            new_epw_dir=str(workdir), new_epw_name=f"{row['district_id']}.epw")
    for k in ("month", "day", "nday"):
        if params.get(k) is not None:
            setattr(m, k, int(params[k]))
    for k, v in A.morphology_overrides(row):
        setattr(m, k, v)
    m.generate()
    m.simulate()
    return m


def main(inputs, params_file, outputs):
    inputs, outputs = Path(inputs), Path(outputs)
    params = json.loads(Path(params_file).read_text())
    weather = pd.read_parquet(inputs / "weather_hourly.parquet")
    morph = pd.read_parquet(inputs / "district_morphology.parquet")
    text, stamps, station = A.epw_from_weather(weather, params.get("station_id"))
    rural = A.rural_temperatures(weather, station)
    frames = []
    with tempfile.TemporaryDirectory() as tmp:
        epw = Path(tmp) / "spine_station.epw"
        epw.write_text(text)
        for row in morph.sort_values("district_id").to_dict("records"):
            m = simulate_district(epw, row, params, tmp)
            h0 = m.simTime.timeInitial - 8
            ts = stamps[h0:h0 + len(m.UCMData)]
            frames.append(A.to_gold(row["district_id"], station, ts,
                                    [u.canTemp - 273.15 for u in m.UCMData], [u.Tdp for u in m.UCMData],
                                    [u.canRHum for u in m.UCMData], rural.loc[ts].to_list()))
            print(f"{row['district_id']}: {len(ts)} hours simulated", flush=True)
    pd.concat(frames, ignore_index=True).to_parquet(outputs / "urban_heat_hourly.parquet", index=False)


if __name__ == "__main__":
    main(*sys.argv[1:4])
