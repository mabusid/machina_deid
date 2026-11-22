#!/usr/bin/env bash
# Resume attempt 4 after the mapping has already been extended. Does not touch mapping.json.
set -eo pipefail
cd /data/machina_deid && source .venv/bin/activate
export DEID_PRIVATE=/root/private
DEST=gs://builders-machina-submissions-use1/teams/b3240ed6-c290-471c-9476-499100a0db6c/attempt-4/
P=/root/private
A=/data/out/attempt-4

rm -rf "$A" "$P/state/attempt-4"
echo "Need a fresh upload token for attempt 4. Paste it in Cursor." > /root/alerts/msg

python scripts/copy_attempt.py --src attempt-3 --dst attempt-4 --skip $P/attempt4-skip.txt > /root/copy4.log 2>&1 &
COPY=$!

python -m deid.transform --rels-file $P/attempt3-rels.txt --out $A/corpus --workers 2

rm -rf "$A/code" && mkdir -p "$A/code"
git archive HEAD | tar -x -C "$A/code"
pip freeze > "$A/code/requirements.lock.txt"
sed "s/attempt-3/attempt-4/g" /data/out/attempt-3/README.txt > "$A/README.txt"
cat >> "$A/README.txt" <<'TXT'

ATTEMPT-4 CHANGES
  - Emails, uncommon person-name pairs and company phrases (Inc/GmbH/Ltd/...) mined from
    PDF page text were added to the mapping. Dictionary-word pairs are not keys. Bare tokens
    shorter than 6 letters from this pass are not keys. Existing keys and pseudonyms are unchanged.
  - Only PDFs were re-processed; every other file is byte-identical to attempt-3.
TXT
cd "$A" && bash /data/machina_deid/scripts/upload_slice.sh "$DEST" --readme README.txt
wait $COPY
tail -2 /root/copy4.log
echo "Attempt 4 processed+uploaded. In Cursor, tell the agent: attempt 4 uploaded" > /root/alerts/msg
