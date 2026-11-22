#!/usr/bin/env bash
# PDF transform + upload for attempt 4. Does not copy (copy_attempt.py is already running)
# and does not rebuild the mapping.
set -eo pipefail
cd /data/machina_deid && source .venv/bin/activate
export DEID_PRIVATE=/root/private
DEST=gs://builders-machina-submissions-use1/teams/b3240ed6-c290-471c-9476-499100a0db6c/attempt-4/
A=/data/out/attempt-4
rm -rf "$A" /root/private/state/attempt-4

python -m deid.transform --rels-file /root/private/attempt3-rels.txt --out $A/corpus --workers 2

rm -rf "$A/code" && mkdir -p "$A/code"
git archive HEAD | tar -x -C "$A/code"
pip freeze > "$A/code/requirements.lock.txt"
sed "s/attempt-3/attempt-4/g" /data/out/attempt-3/README.txt > "$A/README.txt"
cat >> "$A/README.txt" <<'TXT'

ATTEMPT-4 CHANGES
  - Email addresses and person phrases that contain a real given name were mined from PDF
    page text and added to the mapping. Bare tokens and dictionary-word or technical phrases
    were not added, so part names and filenames stay as they were in attempt 3.
  - Existing keys and pseudonyms are unchanged. Only PDFs were re-processed; every other
    file is byte-identical to attempt-3.
TXT
cd "$A" && bash /data/machina_deid/scripts/upload_slice.sh "$DEST" --readme README.txt
echo "Attempt 4 processed+uploaded. In Cursor, tell the agent: attempt 4 uploaded" > /root/alerts/msg
