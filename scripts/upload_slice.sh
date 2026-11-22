#!/usr/bin/env bash
# Upload hook for `deid.batch transform --upload-cmd`; runs inside attempt-N/.
# Usage: upload_slice.sh gs://.../attempt-N/ [extra upload.py args, e.g. --readme README.txt]
# Upload tokens are write-only (no storage.objects.list), hence --no-resume; each slice's
# corpus/ holds only that slice's files. Waits for a token in $TOKEN_FILE; raises $ALERT_DIR/need_token while upload.py waits for a fresh one.
set -uo pipefail
DEST="$1"; shift
TOK=${TOKEN_FILE:-/root/token.txt}
FLAG=${ALERT_DIR:-/root/alerts}/need_token
UPLOAD_PY=${UPLOAD_PY:-/root/upload.py}
mkdir -p "$(dirname "$FLAG")"

while [ ! -s "$TOK" ]; do touch "$FLAG"; sleep 10; done
rm -f "$FLAG"

MACHINA_UPLOAD_TOKEN="$(cat "$TOK")" python3 "$UPLOAD_PY" --dest "$DEST" \
  --corpus corpus --code code --token-file "$TOK" --workers 16 --no-resume "$@" 2>&1 |
while IFS= read -r line; do
  printf '%s\n' "$line"
  case "$line" in
    *"ran out"*) touch "$FLAG" ;;
    *"Got a new token"*|Done*) rm -f "$FLAG" ;;
  esac
done
rc=${PIPESTATUS[0]}
[ "$rc" -eq 0 ] && rm -f "$FLAG"
exit "$rc"
