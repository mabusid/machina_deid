#!/usr/bin/env bash
# Attempt 4: emails, uncommon person names and company phrases from PDF page text.
# Existing keys stay byte-identical. Only PDFs are re-made; the rest is copied from attempt-3.
set -eo pipefail
cd /data/machina_deid && source .venv/bin/activate
export DEID_PRIVATE=/root/private
DEST=gs://builders-machina-submissions-use1/teams/b3240ed6-c290-471c-9476-499100a0db6c/attempt-4/
P=/root/private
A=/data/out/attempt-4

echo "Need a fresh upload token for attempt 4 (gs://.../attempt-4/). Paste it in Cursor." > /root/alerts/msg

[ -f $P/mapping.attempt3.json ] || cp $P/mapping.json $P/mapping.attempt3.json
cp $P/mapping.attempt3.json $P/mapping.json
python scripts/pdf_idents.py --rels $P/attempt3-rels.txt

python - <<'PY'
import json
sel = [r for r in open("/root/private/attempt3-rels.txt", encoding="utf-8").read().split("\n") if r.lower().endswith(".pdf")]
last = {}
for line in open("/root/private/state/attempt-3/status.jsonl", encoding="utf-8"):
    d = json.loads(line)
    last[d["rel"]] = d
skip = [last[r]["dst"].split("/attempt-3/corpus/", 1)[1] for r in sel if r in last]
open("/root/private/attempt4-skip.txt", "w", encoding="utf-8").write("\n".join(skip))
print(len(sel), "pdf rels,", len(skip), "skip paths")
PY

python scripts/copy_attempt.py --src attempt-3 --dst attempt-4 --skip $P/attempt4-skip.txt > /root/copy4.log 2>&1 &
COPY=$!

python -m deid.transform --rels-file $P/attempt3-rels.txt --out $A/corpus --workers 2

rm -rf "$A/code" && mkdir -p "$A/code"
git archive HEAD | tar -x -C "$A/code"
pip freeze > "$A/code/requirements.lock.txt"
sed "s/attempt-3/attempt-4/g" /data/out/attempt-3/README.txt > "$A/README.txt"
cat >> "$A/README.txt" <<'TXT'

ATTEMPT-4 CHANGES
  - Emails, uncommon person-name pairs and company phrases (a legal suffix such as Inc,
    GmbH, Ltd) were mined from PDF page text and added to the mapping. A name is kept
    only when neither word is a dictionary word, so engineering phrases stay put.
    Companies are added as the whole phrase only. Existing keys and pseudonyms are unchanged.
  - Only PDFs were re-processed; every other file is byte-identical to attempt-3.
TXT
cd "$A" && bash /data/machina_deid/scripts/upload_slice.sh "$DEST" --readme README.txt
wait $COPY
tail -2 /root/copy4.log
echo "Attempt 4 processed+uploaded. In Cursor, tell the agent: attempt 4 uploaded" > /root/alerts/msg
