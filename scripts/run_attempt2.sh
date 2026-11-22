#!/usr/bin/env bash
# Attempt 2: re-process only PDF + OLE files (selected from attempt-1 status), upload them,
# while scripts/copy_attempt.py copies every other attempt-1 object server-side.
set -eo pipefail
cd /data/machina_deid && source .venv/bin/activate
export DEID_PRIVATE=/root/private
DEST=gs://builders-machina-submissions-use1/teams/b3240ed6-c290-471c-9476-499100a0db6c/attempt-2/
SEL=/root/private/attempt2-rels.txt

python - <<'PY'
import os
from pathlib import Path
from deid.batch import download
from deid.manifest import load_manifest
sel = set(open("/root/private/attempt2-rels.txt", encoding="utf-8").read().split("\n"))
for root, _d, files in os.walk("/data/input"):
    for n in files:
        p = os.path.join(root, n)
        if os.path.relpath(p, "/data/input") not in sel:
            os.remove(p)
rows = [r for r in load_manifest("/data/manifest.tsv") if r.rel in sel]
download(rows, Path("/data/input"), 32)
PY

python -m deid.transform --rels-file "$SEL" --out /data/out/attempt-2/corpus --workers 2

A=/data/out/attempt-2
rm -rf "$A/code" && mkdir -p "$A/code"
git archive HEAD | tar -x -C "$A/code"
pip freeze > "$A/code/requirements.lock.txt"
sed "s/attempt-1/attempt-2/g" /data/out/attempt-1/README.txt > "$A/README.txt"
cat >> "$A/README.txt" <<'TXT'

ATTEMPT-2 CHANGES (same mapping as attempt-1; keys and owners byte-identical)
  - PDF page text: each identifier found in a page's text is redacted and its pseudonym is
    written in the same box (PyMuPDF redactions; images and line art untouched).
  - OLE property sets (Author, Last saved by, ...): every string value is pseudonymized,
    including short or generic account names; non-generic ones also in the other streams.
  - Only PDF and OLE files were re-processed; every other file is byte-identical to attempt-1
    (copied server-side).
TXT
cd "$A" && bash /data/machina_deid/scripts/upload_slice.sh "$DEST" --readme README.txt
echo "Attempt 2 processed+uploaded. In Cursor, tell the agent: attempt 2 uploaded" > /root/alerts/msg
