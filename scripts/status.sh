#!/usr/bin/env bash
# Mac side: one-screen status of the droplet run. Usage: bash scripts/status.sh
HOST=${DROPLET:-root@157.245.186.31}
ssh -o ConnectTimeout=15 "$HOST" 'bash -s' <<'EOF'
echo "== Harvest"; tail -n 2 /root/harvest.log 2>/dev/null
[ -s /root/resolve.log ] && { echo "== Mapping"; tail -n 3 /root/resolve.log; }
[ -s /root/transform.log ] && { echo "== Attempt"; grep -E "^\[transform\]|uploading|Done|WARNING|Error" /root/transform.log | tail -n 4; }
echo "== Disk"; df -h /data | tail -n 1
a=$(cat /root/alerts/current 2>/dev/null)
echo "== Needs you: ${a:-nothing right now}"
EOF
