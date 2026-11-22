# Setup

How to get a machine ready to work on this project. Read `CLAUDE.md` first for the task, the scoring and the rules.

Everything starts from this GitHub repo: each Mac clones it to develop on a small sample, and one shared VM clones it to run the full corpus.

## 1. GitHub access
- Get added as a collaborator on this repo and accept the invite.
- Add your Mac's SSH key to GitHub (Settings → SSH and GPG keys):
  ```bash
  ls ~/.ssh/id_ed25519.pub || ssh-keygen -t ed25519
  pbcopy < ~/.ssh/id_ed25519.pub
  ssh -T git@github.com              # check: greets you by username
  ```

## 2. Case-sensitive workspace (Mac)
The corpus needs a case-sensitive filesystem, and the default macOS disk isn't one.
```bash
hdiutil create -size 5g -fs "Case-sensitive APFS" -type SPARSE -volname deid ~/deid.sparseimage
hdiutil attach ~/deid.sparseimage      # re-run after every reboot
cd /Volumes/deid
git clone git@github.com:mabusid/machina_deid.git
cd machina_deid
```

## 3. Python (Mac)
```bash
python3 --version                      # needs 3.11+
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install --only-binary=:all: -r requirements.txt
python -m spacy download en_core_web_sm
python -c "import pymupdf, olefile, ezdxf, spacy; print('ok')"
```
- `--only-binary=:all:` avoids compiling packages. On older macOS, Homebrew may say "no bottle available".
- If `pikepdf` won't install, skip it on the Mac. The VM installs it fine.
- exiftool: use the macOS package from exiftool.org if `brew install exiftool` fails.
- Import PyMuPDF as `pymupdf`, not `fitz`.

## 4. Sample data (Mac, never commit it)
```bash
curl -fsSLO https://machina-input.joinbuilders.org/get-input.sh
bash get-input.sh --limit 100                              # into ./input (gitignored)
bash get-input.sh --prefix sources/existing/ --limit 10    # other sources, when you need more formats
```
The first 100 files are mostly SolidWorks: `.SLDPRT` parts, `.SLDASM` assemblies, some STEP, zip and 7z.
About 95% of the corpus is under `sources/github/`.

## 5. Shared VM (one per team)
The full 140 GB corpus lives only here. One person creates it, and everyone else is added by SSH key. Expected cost is about $20 for the weekend.

**Create it (VM owner, DigitalOcean dashboard):**
1. Go to **Create → Droplets**: region New York, **Ubuntu 24.04 LTS**, **General Purpose 8 vCPU / 32 GB**.
2. Click **Add Volume**: **500 GB**, **Automatically Format & Mount**, **ext4**.
3. Under **Authentication → SSH Key**, add every teammate's public key.
4. Create it and share the IP with the team.

**Set it up (VM owner):**
```bash
ssh root@<VM_IP>
df -h                                   # a ~500G disk under /mnt/volume_...
ln -s /mnt/volume_* /data
apt update && apt install -y git tmux python3-venv python3-pip unzip p7zip-full aria2 libimage-exiftool-perl
tmux new -s deid                        # always work in tmux; reattach: tmux attach -t deid
```

**Start the full download right away.** It runs while everyone codes:
```bash
cd /data
curl -fsSLO https://machina-input.joinbuilders.org/get-input.sh
bash get-input.sh --dest /data/input --jobs 32 --aria2    # Ctrl-b d to detach
```
When it finishes, run the same command again. It should report everything complete. Expect 188,722 files.

**Clone the repo onto the VM** (read-only deploy key):
```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub     # GitHub repo → Settings → Deploy keys → Add (read-only)
cd /data && git clone git@github.com:mabusid/machina_deid.git
cd machina_deid && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

**Adding a teammate later:** append their public key to `~/.ssh/authorized_keys` on the VM.

**Rules:**
- Never edit `/data/input`. Outputs go to `/data/out/<attempt>/`.
- Only `main` runs on the full corpus. Only one person uploads and submits.
- After the deadline, destroy the Droplet AND the Volume. A detached volume is still billed.

## 6. How we work
- Work on a branch per handler, e.g. `sldworks-handler`. Merge to `main` once it passes on the sample.
- Every handler is `handle(src, dst, mapping) -> status`. On any error or failed validation, the original file is copied unchanged.
- Pseudonyms keep the same byte length and casing as the original, so binary files stay intact.
- Never commit `input/`, `output/`, `corpus/`, `sample.tsv` or the mapping DB. They contain real names.
- Log design decisions in `DECISIONS.md` and scored attempts in `SCORES.md`.
- Deadline: Sunday 11:00 AM ET. The team has 20 scored attempts in total.

## Each session (Mac)
```bash
hdiutil attach ~/deid.sparseimage
cd /Volumes/deid/machina_deid && source .venv/bin/activate
git pull && git checkout <your-branch>
claude
```
