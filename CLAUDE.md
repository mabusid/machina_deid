# Machina CAD De-ID — Builders Buildathon

Track page: https://www.joinbuilders.org/buildathon/tracks/machina-deid
Deadline: **Sunday 11:00 AM ET**. Prize: $5,000 for top score.

## The task
De-identify an engineering corpus: replace names and other identifying info with
**consistent pseudonyms** (same real name → same pseudonym everywhere), while keeping
every file usable and cross-file links intact.

- Input: 188,722 files, 139.7 GB — PDFs, drawings, SolidWorks, Inventor, neutral CAD
  (STEP/IGES/DXF), images, archives.
- Download with `get-input.sh` into `./input/` (supports `--limit 100`, resume,
  `--prefix`, `--jobs`). Source: machina-input.joinbuilders.org
- Must run on a **case-sensitive filesystem**.
- Submit: upload `corpus/` with `upload.py` to the team's Builders folder, then submit
  that location on the track page.

## Scoring
- 1,000 private checks; score = checks passed. Category pass counts are shown, not
  individual checks.
- Checks cover consistent name replacement AND engineering files remaining usable.
- Baseline (input copied unchanged) = **292**. Breaking files likely costs more than
  missing names — never corrupt a file; if unsure, copy it unchanged.
- **Max 20 scored attempts for the team.** Ties go to the earlier attempt.
  Scorer version: `machina-deid-1`. Log every attempt in `SCORES.md`.

## Approach
1. Survey formats on the 100-file sample (counts by extension; inspect with
   `exiftool`, `strings`, text editor for STEP/DXF).
2. Build a global name list. Mine predictable places first: title blocks
   ("Drawn by", "Checked by", "Approved"), metadata (Author, Company, Last saved by),
   emails, paths. Then NER (spaCy / Presidio) for the rest.
3. One persistent mapping (SQLite) real → pseudonym, deterministic (keyed hash) so
   parallel workers and batches agree. Handle variants: "J. Smith", "SMITH",
   "jsmith@…", "jsmith" in paths.
4. Per-format handlers:
   - STEP / IGES / DXF: plain text; STEP header has author/organization fields.
   - PDF: metadata via pikepdf; page text via PyMuPDF (subset fonts, split strings).
   - SolidWorks / Inventor: binary, often OLE compound docs. Use **length-preserving**
     replacement (pad pseudonym to same byte length). Check ASCII and UTF-16LE.
     These files reference other files by name.
   - Images: EXIF/XMP metadata. OCR of burned-in text is last priority.
   - Archives: unpack, process recursively, repack in the same format.
5. Renamed files/folders: record every rename in the mapping and rewrite references
   inside other files, or assemblies break.
6. First scored attempt early (metadata + text formats, everything else copied),
   then iterate on the weakest categories.

## Infrastructure
- Dev: Macs, 100-file sample on a case-sensitive APFS sparse image.
- Full run: DigitalOcean droplet (Ubuntu 24.04, 8 vCPU) + 500 GB ext4 volume at
  `/mnt/volume_*`. Work inside `tmux`. Destroy droplet AND volume after the deadline.
- Process at scale with multiprocessing; make runs resumable.

## Repo rules
- **Never commit data**: input, output, corpus, unpacked archives, or the name mapping
  DB (it contains real names). See `.gitignore`.
- Code, notes, and `SCORES.md` only.
- When we make a design decision, add an entry to DECISIONS.md using its template.
