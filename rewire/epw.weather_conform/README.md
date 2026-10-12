# epw.weather_conform

Conformer, MIT, python runtime. Bronze `epw/<version>/*.epw` becomes silver `weather_hourly` and `id_bridge`.

* EPW hour `h` on local date `d` becomes timestamp `d + h hours - UTC offset` in UTC, so it marks the end of the hour (Singapore is +8).
* EPW missing sentinels (99.9, 999, 9999, ...) become null.
* Extension columns `horizontal_ir_wm2`, `latitude_deg`, `longitude_deg`, `utc_offset_h`, `elevation_m` and `ground_temps_json`
  are kept so `uwg.urban_heat` can rebuild a model-ready EPW. `rewire/tests` checks that the rebuild round-trips every field UWG reads.
* Station hub id `wmo-<WMO>`. `id_bridge` maps `wmo:486980` and `epw:SGP_Singapore.486980_IWEC` onto it.

Golden: `golden/singapore_iwec`. Expected values come from the upstream `uwg.weather.Weather` reader.
