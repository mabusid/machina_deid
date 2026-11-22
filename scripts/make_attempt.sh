#!/usr/bin/env bash
# Full attempt: transform -> verify -> README -> code snapshot.
# Usage: scripts/make_attempt.sh N [--reharvest]
# Result: /data/out/attempt-N/{corpus,code,README.txt}, ready for upload.py.
set -euo pipefail
N=${1:?attempt number}
DATA=${DEID_DATA:-/data}
ATT="$DATA/out/attempt-$N"
WORKERS=${WORKERS:-$(nproc)}
cd "$(dirname "$0")/.."

if [[ "${2:-}" == "--reharvest" || ! -f "$DATA/private/harvest.json" ]]; then
  python -m deid.harvest --workers "$WORKERS"
fi
python -m deid.resolve
python -m deid.transform --out "$ATT/corpus" --workers "$WORKERS"
python -m deid.verify --out "$ATT/corpus" || echo "!! verify reported problems: check $DATA/private/state/attempt-$N/verify.json"

rm -rf "$ATT/code" && mkdir -p "$ATT/code"
git archive HEAD | tar -x -C "$ATT/code"
pip freeze > "$ATT/code/requirements.lock.txt"
python -m deid.readme --out "$ATT/corpus" > "$ATT/README.txt"

echo "objects in corpus: $(find "$ATT/corpus" -type f | wc -l)"
du -sh "$ATT/corpus"
echo "Ready: $ATT  (upload corpus/, code/, README.txt with upload.py)"
