# rewire/ - Urban Weather Generator on the sg-urban-spine

UWG is wired into the [sg-urban-spine](https://github.com/tetratorus/sg-urban-spine) contract
([spec/LAYERS.md](https://github.com/tetratorus/sg-urban-spine/blob/main/spec/LAYERS.md)). The scientific code in
`uwg/` is **not modified**. This directory only adds descriptors, thin adapters, golden tests and a GPL runtime image.

```
bronze:epw ──epw.weather_conform──> silver.weather_hourly (+ silver.id_bridge station rows) ─┐
silver.buildings + land_cover + districts ──morphology.district──> gold district_morphology ─┴─uwg.urban_heat──> gold urban_heat_hourly
```

| transform | kind | runtime | licence of the code that runs | readiness |
|---|---|---|---|---|
| [`epw.weather_conform`](epw.weather_conform/) | conformer | `python` (in-process) | MIT, does not import uwg | RL6 |
| [`morphology.district`](morphology.district/) | transform | `python` (in-process) | MIT, does not import uwg | RL6 |
| [`uwg.urban_heat`](uwg.urban_heat/) | transform | `docker` `tetratorus/uwg-urban-heat:0.1.0` | GPL-3 (uwg) + MIT adapter | RL6 |

## Quick start

```bash
pip install 'git+https://github.com/tetratorus/sg-urban-spine@main'
docker build -f rewire/uwg.urban_heat/Dockerfile -t tetratorus/uwg-urban-heat:0.1.0 .   # from the repo root
spine --path rewire validate
spine --path rewire test               # 4 golden cases
python -m pytest rewire/tests -q       # integration tests (docker case skipped if the image is missing)
rewire/e2e.sh                          # bronze -> silver -> gold -> spine serve, in a temporary lake
```

## GPL boundary

UWG is GPL-3.0. Spine code and the MIT adapters never `import uwg`. `rewire/tests/test_rewire.py::test_mit_code_never_imports_uwg`
checks this on every MIT file.

* `uwg.urban_heat` uses the spine **docker** runtime (directory contract `{inputs}` `{params}` `{outputs}`).
  Only GPL code imports uwg: `uwg.urban_heat/runtime/run_uwg.py` and `tools/freeze_goldens.py`. Both are marked
  `SPDX-License-Identifier: GPL-3.0-or-later` and run only inside the image.
* The MIT `uwg.urban_heat/adapter.py` does the mapping (silver weather -> EPW text, morphology row -> UWG attributes,
  results -> gold table). It is copied into the image and imported *by* the GPL runner. GPL code can import MIT
  code; the reverse never happens.
* Only parquet files cross the boundary.

## Python version: the GPL runtime uses Python 3.11

Upstream CI tests on Python 3.10 and 3.11. Python 3.12 changed `sum()` of floats to compensated summation
(`sum([0.1]*10)` is `1.0` on 3.12 and `0.9999999999999999` on 3.11). We measured the effect here:

* upstream `pytest tests/`: **61 passed on 3.11**. On 3.12 there are **5 failures**: `test_RSMDef::test_rsm_dissipation_bougeault`,
  `test_UWG::test_read_input` and `test_procMat` (10 road layers instead of 11), and `test_element::test_SurfFlux_with_waterStorage_middle`
  and `test_SurfFlux_integration`.
* Singapore January run: canyon air temperature changes by up to 0.0024 K between 3.11 and 3.12.

So the image is pinned to `python:3.11-slim`. Golden values were frozen in that image and are compared at `atol 1e-9`.
`tests/test_cli.py` also needs `pydantic<2` (`uwg-schema==0.2.11`); with that pin, all 6 CLI tests pass on 3.11.

## Golden tests (`spine test`)

| case | expected values come from |
|---|---|
| `epw.weather_conform/singapore_iwec` | upstream readers `uwg.weather.Weather` and `UWG._read_epw` on `resources/SGP_Singapore.486980_IWEC.epw` |
| `morphology.district/singapore_reference` | `D-SG-REF` = UWG's own `resources/initialize_singapore.uwg` (bldHeight 10, bldDensity 0.5, verToHor 0.8, grass 0.1, tree 0.1). The synthetic block is built to hit those values. `D-SG-DENSE` is hand-computed |
| `uwg.urban_heat/singapore_jan` | unmodified UWG run directly on `initialize_singapore.uwg` and the **original** EPW, one run per district (`tools/freeze_goldens.py`). This proves the spine path (rebuilt EPW, morphology as attributes) gives the same answer |
| `uwg.urban_heat/matlab_reference` | upstream MATLAB output `tests/matlab_ref/matlab_output/SGP_Singapore.486980_IWEC_UWG_Matlab.epw`. Tolerances come from the measured Python-vs-MATLAB gap (air temperature max 0.333 K, RH max 1.91 %) |

Regenerate: `python rewire/tools/make_fixtures.py` (inputs, MIT) then
`docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/work" tetratorus/uwg-urban-heat:0.1.0 python /opt/rewire/tools/freeze_goldens.py /work`.

## IDs (GERS-style `id_bridge`)

Stations use the hub id `wmo-<WMO index>` (`wmo-486980`). The conformer writes `id_bridge` rows that map the WMO number (`source=wmo`)
and the EPW dataset name (`source=epw`, `SGP_Singapore.486980_IWEC`) onto that hub. Districts, buildings and land-cover cells keep
their silver hub ids; UWG has no ids of its own.

## Upstream changes

None. No file outside `rewire/` was changed.

## Known gaps

* UWG simulates one rural station per run. Each district is a separate single-column UWG run, so districts do not exchange heat.
* Base parameters other than morphology (building mix, albedos, `charLength` 1000 m, `zone 1A`) come from `initialize_singapore.uwg`.
* `vertohor` counts every building perimeter as facade, so shared party walls of attached buildings are counted too.
* The IWEC 2001 EPW is ASHRAE-licensed (see `epw.weather_conform/transform.yaml`). For production, use MSS station data.
* Silver `buildings` / `land_cover` / `districts` conformers belong to other repos. `e2e.sh` seeds them from the golden fixture.
