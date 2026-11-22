#!/usr/bin/env bash
# Mac side: pop a notification (with sound) when the droplet needs you; repeats every 10 min.
HOST=${DROPLET:-root@157.245.186.31}
last=0
while true; do
  msg=$(ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" 'cat /root/alerts/current 2>/dev/null')
  now=$(date +%s)
  if [ -n "$msg" ] && [ $((now - last)) -ge 600 ]; then
    osascript -e "display notification \"${msg//\"/}\" with title \"Machina De-ID\" sound name \"Glass\""
    last=$now
  fi
  [ -z "$msg" ] && last=0
  sleep 60
done
