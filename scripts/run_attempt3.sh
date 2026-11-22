#!/usr/bin/env bash
# Attempt 3: add title-block names mined from PDF page text to the mapping (existing keys and
# pseudonyms unchanged), re-process only PDFs, copy every other attempt-2 object server-side.
set -eo pipefail
cd /data/machina_deid && source .venv/bin/activate
export DEID_PRIVATE=/root/private
DEST=gs://builders-machina-submissions-use1/teams/b3240ed6-c290-471c-9476-499100a0db6c/attempt-3/
P=/root/private
A=/data/out/attempt-3
LOG=/root/attempt3.log

[ -f $P/mapping.attempt2.json ] || cp $P/mapping.json $P/mapping.attempt2.json
cp $P/mapping.attempt2.json $P/mapping.json
python scripts/pdf_names.py --rels $P/attempt2-rels.txt

python - <<'PY'
import json
sel = [r for r in open("/root/private/attempt2-rels.txt", encoding="utf-8").read().split("\n")
       if r.lower().endswith(".pdf")]
last = {}
for line in open("/root/private/state/attempt-2/status.jsonl", encoding="utf-8"):
    d = json.loads(line)
    last[d["rel"]] = d
open("/root/private/attempt3-rels.txt", "w", encoding="utf-8").write("\n".join(sel))
skip = [last[r]["dst"].split("/attempt-2/corpus/", 1)[1] for r in sel]
open("/root/private/attempt3-skip.txt", "w", encoding="utf-8").write("\n".join(skip))
print(len(sel), "pdf rels")
PY

python scripts/copy_attempt.py --src attempt-2 --dst attempt-3 --skip $P/attempt3-skip.txt > /root/copy3.log 2>&1 &
COPY=$!

python -m deid.transform --rels-file $P/attempt3-rels.txt --out $A/corpus --workers 2

rm -rf "$A/code" && mkdir -p "$A/code"
git archive HEAD | tar -x -C "$A/code"
pip freeze > "$A/code/requirements.lock.txt"
sed "s/attempt-2/attempt-3/g" /data/out/attempt-2/README.txt > "$A/README.txt"
cat >> "$A/README.txt" <<'TXT'

ATTEMPT-3 CHANGES
  - Person names mined from PDF page text near title-block labels (Drawn / Checked /
    Approved / Designer / Gezeichnet / Geprueft / Erstellt / Dibujado / ...), plus their
    initial and surname variants, were added to the mapping. Existing keys and pseudonyms
    are unchanged (the pseudonymizer is pre-seeded with every existing token mapping).
  - Only PDFs were re-processed; every other file is byte-identical to attempt-2.
TXT
cd "$A" && bash /data/machina_deid/scripts/upload_slice.sh "$DEST" --readme README.txt
wait $COPY
tail -2 /root/copy3.log
echo "Attempt 3 processed+uploaded. In Cursor, tell the agent: attempt 3 uploaded" > /root/alerts/msg
