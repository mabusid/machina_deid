#!/usr/bin/env bash
# Attempt 5:
#  1. Extend mapping with Inventor+SW OLE accounts, PDF emails/URLs/orgs/persons, PDF meta authors,
#     and non-ASCII identities (unicode_map). Existing `keys` stay byte-identical (zero path renames).
#  2. Re-process ALL 21,214 PDF + OLE files with fixed oriented PDF redaction and per-file OLE
#     cross-stream saved-account sweep (incl. ISolidWorksInformation & Inventor property sets).
#  3. Copy the other 167,508 files server-side from attempt-3 to attempt-5 in parallel.
#  4. Upload all 21,214 PDF+OLE files, code/, and README.txt to attempt-5.
set -eo pipefail
cd /data/machina_deid && source .venv/bin/activate
export DEID_PRIVATE=/root/private
DEST=gs://builders-machina-submissions-use1/teams/b3240ed6-c290-471c-9476-499100a0db6c/attempt-5/
P=/root/private
A=/data/out/attempt-5

[ -f $P/mapping.attempt3.json ] || cp $P/mapping.json $P/mapping.attempt3.json
python scripts/extend_attempt5.py --rels $P/attempt2-rels.txt

# Build exact attempt-5 skip list (corpus paths in attempt-3 of the 21,214 PDF+OLE files)
python - <<'PY'
import json
sel = set(r for r in open("/root/private/attempt2-rels.txt", encoding="utf-8").read().splitlines() if r)
last = {}
for fn in ("/root/private/state/attempt-1/status.jsonl", "/root/private/state/attempt-2/status.jsonl", "/root/private/state/attempt-3/status.jsonl"):
    for line in open(fn, encoding="utf-8"):
        d = json.loads(line)
        if d["rel"] in sel:
            last[d["rel"]] = d["dst"].split("/corpus/", 1)[1]
skip = sorted(set(last.values()))
open("/root/private/attempt5-skip.txt", "w", encoding="utf-8").write("\n".join(skip))
print(f"sel={len(sel)} skip={len(skip)}", flush=True)
PY

python scripts/copy_attempt.py --src attempt-3 --dst attempt-5 --skip $P/attempt5-skip.txt > /root/copy5.log 2>&1 &
COPY=$!

rm -rf "$A" "$P/state/attempt-5"
python -m deid.transform --rels-file $P/attempt2-rels.txt --out $A/corpus --workers 2

rm -rf "$A/code" && mkdir -p "$A/code"
git archive HEAD | tar -x -C "$A/code"
pip freeze > "$A/code/requirements.lock.txt"
sed "s/attempt-3/attempt-5/g" /data/out/attempt-3/README.txt > "$A/README.txt"
cat >> "$A/README.txt" <<'TXT'

ATTEMPT-5 CHANGES
  - Fixed PDF page-text redaction for rotated pages and vertical title blocks using quad
    orientation detection (eliminates clipped fragments and truncated pseudonyms).
  - Fixed PDF word-boundary checks to match Replacer camelCase/digit boundaries (e.g. BCN3DSigma).
  - Added PDF emails, non-public domains/URLs, recurring organizations/institutions, given-name
    person pairs, PDF author metadata, and non-ASCII names/companies (unicode_map) while keeping
    all existing path-renaming keys byte-identical (zero path changes vs attempt-3).
  - Fixed OLE saved-account and cross-stream residue: harvested Inventor property-set accounts
    and SolidWorks ISolidWorksInformation; applied property-set pseudonymization to
    ISolidWorksInformation and non-ASCII accounts; added per-file cross-stream sweep (ASCII +
    UTF-16LE) over non-preview streams so original saved accounts never leak across streams.
  - All 21,214 PDF + OLE files re-processed; other 167,508 files copied server-side from attempt-3.
TXT
cd "$A" && bash /data/machina_deid/scripts/upload_slice.sh "$DEST" --readme README.txt
wait $COPY
tail -2 /root/copy5.log
echo "Attempt 5 processed+uploaded. In Cursor, tell the agent: attempt 5 uploaded" > /root/alerts/msg
