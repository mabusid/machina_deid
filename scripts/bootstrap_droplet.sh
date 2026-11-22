#!/usr/bin/env bash
# One-time droplet setup (Ubuntu 24.04, run as root inside tmux).
# Usage: bash scripts/bootstrap_droplet.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
DATA=/data
[[ -e $DATA ]] || ln -s /mnt/volume_* $DATA

if ! swapon --show | grep -q swapfile; then  # small droplets: avoid OOM on big archives
  fallocate -l 8G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
fi

apt-get update
apt-get install -y git tmux python3-venv python3-pip unzip p7zip-full aria2 curl \
  libimage-exiftool-perl poppler-utils wamerican

cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cd $DATA
[[ -f manifest.tsv ]] || curl -fsSLO https://machina-input.joinbuilders.org/manifest.tsv
[[ -f get-input.sh ]] || curl -fsSLO https://machina-input.joinbuilders.org/get-input.sh
mkdir -p $DATA/private $DATA/out
chmod 700 $DATA/private
echo "Next: tmux new-window 'cd $DATA && bash get-input.sh --dest $DATA/input --jobs 32 --aria2'"
