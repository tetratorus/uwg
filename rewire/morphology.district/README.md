# morphology.district

Transform, MIT, python runtime. Silver `districts` + `buildings` + `land_cover` become gold `district_morphology`
(one row per district). Planar EPSG:3414 metres; A = district area.

| column | formula | UWG `.uwg` key |
|---|---|---|
| `bldheight` | Σ h·footprint / Σ footprint | `bldHeight` |
| `blddensity` | Σ footprint / A | `bldDensity` |
| `vertohor` | Σ perimeter·h / A | `verToHor` |
| `grasscover` | Σ grass_cover·area(cell ∩ district) / A | `grasscover` |
| `treecover` | Σ tree_cover·area(cell ∩ district) / A | `treeCover` |

`h` = `height_m`, otherwise `storeys × storey_height_m` (default 3.05 m, UWG's default floor height).
If `blddensity + grasscover + treecover > 1`, the transform raises an error, the same check UWG makes.

Golden: `golden/singapore_reference`. A synthetic 100 m block reproduces UWG's own Singapore parameters.
