#!/usr/bin/env bash
# Droplet side: every minute, write the current "needs you" message to $ALERT_DIR/current
# (empty when nothing is needed) and push it to ntfy.sh/$NTFY_TOPIC if set (at most every 10 min).
# Other scripts can drop a one-off message into $ALERT_DIR/msg.
ALERT_DIR=${ALERT_DIR:-/root/alerts}
TOK=${TOKEN_FILE:-/root/token.txt}
mkdir -p "$ALERT_DIR"
last=0
while true; do
  msg=""
  if [ -s "$ALERT_DIR/msg" ]; then
    msg=$(cat "$ALERT_DIR/msg")
  elif [ -e "$ALERT_DIR/need_token" ]; then
    msg="Upload paused: send a fresh upload token"
  elif pgrep -f "deid.batch transform" >/dev/null && [ -s "$TOK" ] &&
       [ $(( $(date +%s) - $(stat -c %Y "$TOK") )) -gt 3000 ]; then
    msg="Upload token expires in under 10 min: send a fresh one"
  fi
  printf '%s' "$msg" > "$ALERT_DIR/current"
  now=$(date +%s)
  if [ -n "$msg" ] && [ -n "${NTFY_TOPIC:-}" ] && [ $((now - last)) -ge 600 ]; then
    curl -fsS -m 20 -H "Title: Machina De-ID" -d "$msg" "https://ntfy.sh/$NTFY_TOPIC" >/dev/null && last=$now
  fi
  [ -z "$msg" ] && last=0
  sleep 60
done
