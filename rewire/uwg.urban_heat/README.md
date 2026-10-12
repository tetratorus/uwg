# uwg.urban_heat

Transform, docker runtime (GPL-3 boundary). Silver `weather_hourly` + gold `morphology.district/district_morphology`
become gold `urban_heat_hourly`, keyed by `district_id`, `timestamp` (UTC).

```bash
docker build -f rewire/uwg.urban_heat/Dockerfile -t tetratorus/uwg-urban-heat:0.1.0 .   # from the repo root
spine --path rewire run uwg.urban_heat --params '{"nday": 7}'
```

Inside the container, `runtime/run_uwg.py` (GPL):
1. rebuilds one EPW from the station's 8760 silver rows (`adapter.epw_from_weather`, MIT)
2. for each district runs `UWG.from_param_file(param_file, epw)`, overrides `bldheight`, `blddensity`, `vertohor`,
   `grasscover` and `treecover` (`adapter.morphology_overrides`), then calls `generate()` and `simulate()`
3. writes `urban_air_temp_c` (UCMData.canTemp), `urban_dew_point_c`, `urban_rh_pct`, `rural_air_temp_c` (station dry bulb)
   and `uhi_c` = urban - rural.

Parameters: `station_id`, `month`, `day`, `nday`, `param_file` (default: UWG's `initialize_singapore.uwg`).

Goldens: `singapore_jan` compares against a direct upstream run on the original files. `matlab_reference` compares against
UWG's MATLAB reference output.
