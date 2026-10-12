#!/usr/bin/env bash
# End-to-end demo: bronze -> silver -> gold -> OGC API Features, in a throwaway lake.
#   SPINE=~/venvs/spine/bin rewire/e2e.sh            (needs docker image tetratorus/uwg-urban-heat:0.1.0)
set -euo pipefail
cd "$(dirname "$0")/.."
BIN=${SPINE:-$(dirname "$(command -v spine)")}
export SPINE_LAKE=${SPINE_LAKE:-$(mktemp -d)/lake} SPINE_PATH=rewire
PORT=${PORT:-8091}
echo "lake: $SPINE_LAKE"

"$BIN/spine" bronze-add epw iwec-2001 resources/SGP_Singapore.486980_IWEC.epw \
  --url https://github.com/ladybug-tools/uwg/blob/master/resources/SGP_Singapore.486980_IWEC.epw \
  --license "ASHRAE IWEC (c) 2001, see EPW COMMENTS 1"

# Stand-in for the buildings / land_cover / districts conformers that live in other repos.
"$BIN/python" - <<'PY'
from pathlib import Path
from spine.lake import Lake, read_table
lake = Lake()
case = Path("rewire/morphology.district/golden/singapore_reference/inputs")
for t in ("districts", "buildings", "land_cover"):
    print("silver", t, lake.silver_write(t, read_table(case / f"{t}.parquet")))
PY

"$BIN/spine" workflow rewire/workflow.yaml

"$BIN/spine" serve --port "$PORT" >/tmp/spine-serve-$PORT.log 2>&1 &
trap 'kill $! 2>/dev/null || true' EXIT
for _ in $(seq 30); do curl -sf "http://127.0.0.1:$PORT/collections" >/dev/null && break; sleep 0.5; done
curl -sf "http://127.0.0.1:$PORT/collections" | "$BIN/python" -c \
  'import json,sys; print("collections:", [c["id"] for c in json.load(sys.stdin)["collections"]])'
curl -sf "http://127.0.0.1:$PORT/collections/gold.uwg.urban_heat.urban_heat_hourly/items?limit=2" | "$BIN/python" -c \
  'import json,sys; d=json.load(sys.stdin); print("gold.uwg.urban_heat.urban_heat_hourly:", d.get("numberMatched"), [f["properties"] for f in d["features"]])'
"$BIN/python" - <<'PY'
from spine.lake import Lake
g = Lake().gold_read("uwg.urban_heat", "urban_heat_hourly")
print(g.groupby("district_id")[["urban_air_temp_c", "rural_air_temp_c", "uhi_c"]].mean().round(3).to_string())
PY
