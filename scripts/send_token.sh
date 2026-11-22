#!/usr/bin/env bash
# Copy the upload token on the track page, then run: bash scripts/send_token.sh
HOST=${DROPLET:-root@157.245.186.31}
t=$(pbpaste | tr -d '[:space:]')
if [ ${#t} -lt 40 ] || [[ "$t" == gs://* ]]; then
  echo "The clipboard doesn't look like an upload token. Copy the token itself and run this again."
  exit 1
fi
printf '%s' "$t" | ssh "$HOST" 'cat > /root/token.txt.new && mv /root/token.txt.new /root/token.txt && rm -f /root/alerts/need_token' &&
  echo "Token sent to the droplet."
