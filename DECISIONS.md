# Decisions log

One entry per decision, newest first. Keep each entry short.
Scores live in SCORES.md; link the attempt number here when a decision is tested.

<!-- Template — copy above the newest entry
## <decision in a few words>
- **Context:** why this came up
- **Options:** A) … B) …
- **Chose:** A, because …
- **Pros:** …
- **Cons / risks:** …
- **Result:** attempt #N, score X → Y, or "reverted"
-->

## Slice runner because the volume is capped at 100 GB
- **Context:** Storage limit increase denied; 140 GB input (126 GB unique) cannot fit
- **Options:** A) Wait for a limit increase. B) `deid.batch`: ~12 GB slices of whole repos; download → harvest/transform → upload → evict, earliest slices kept resident
- **Chose:** B
- **Pros:** Fits any disk; resumable; same handlers and mapping as the single-pass run
- **Cons / risks:** Each pass re-downloads what was evicted; upload.py must tolerate partial local folders (to verify); token expiry prompts pause the run
- **Result:** —

## Small droplet (2 vCPU / 2 GB) + volume, not a big VM
- **Context:** Budget allows only Basic 2 vCPU / 2 GB / 60 GB in SFO2
- **Options:** A) Stream batches through the 60 GB disk (re-download 140 GB per pass). B) Add a block-storage volume (billed hourly, ≈ $0.10/GB-month) and keep the pipeline as is
- **Chose:** B, with files ≥ 150 MB processed in line-aligned chunks (1 worker) and 8 GB swap on the volume
- **Pros:** One download; chunked path verified byte-identical to the in-memory path on the sample
- **Cons / risks:** A full transform takes hours on 2 cores, so fewer scored attempts; droplet can be resized temporarily for big runs
- **Result:** —

## Binary files: only edit strings that cannot be random bytes
- **Context:** Compressed CAD streams are random bytes; a 3–4 letter key matches there by chance. Estimated hundreds of corrupted files corpus-wide with naive string replacement
- **Options:** A) Edit every printable run ≥ 8. B) ASCII runs ≥ 16 chars, or shorter only if NUL-terminated, keys ≥ 4 letters; UTF-16LE runs always (alternating NULs never occur by chance)
- **Chose:** B
- **Pros:** Expected random corruptions ≈ 0; property-set and path strings still covered
- **Cons / risks:** Short length-prefixed strings (Parasolid, Solid Edge) keep some names. Visible in verify leak report
- **Result:** —

## OLE files: edit streams, zero free/slack sectors, verify every stream
- **Context:** Raw edits renamed OLE directory entries ("Info", "Styles") and stale copies of names survived in free sectors
- **Options:** A) Raw file edit. B) olefile write_stream per stream (same size) + zero free sectors, free mini-sectors and stream slack; re-read every stream and compare
- **Chose:** B. 20/20 sample OLE files (SolidWorks, Inventor, Solid Edge) pass, 0–1 raw leaks left
- **Result:** —

## SQLite: rewrite through SQL, not bytes
- **Context:** Byte edits broke index order (integrity_check failed) in step.parts catalog DBs
- **Chose:** deserialize → UPDATE text columns with the replacer → REINDEX → VACUUM → integrity_check; virtual tables fall back
- **Result:** —

## Three stages with a frozen mapping
- **Context:** Parallel workers writing a shared SQLite mapping would lock and miss cross-file variants
- **Options:** A) Mapping updated during processing. B) harvest (parallel, read-only) → resolve (single-threaded, deterministic, keyed hash) → transform (parallel, read-only Aho-Corasick)
- **Chose:** B
- **Pros:** Consistent pseudonyms everywhere; resolve is reviewable (`private/review.tsv`) before any file is written; easy to add `extra_entities.tsv` / `exclude.txt`
- **Cons / risks:** Two passes over the data (harvest ≈ 15 min on 16 cores)
- **Result:** —

## Keys: distinctive tokens only; common words never standalone
- **Context:** Repo names and orgs contain dictionary words ("Desktop", "robot", "Styles"); mapping those would rewrite format data everywhere
- **Chose:** Whole identity phrases + variants (J. Smith, jsmith, smith.j …) are keys; single tokens only if not a dictionary word / allowlisted, ≥ 4 letters (3 only for a whole owner/user value). Owners of `owner__repo` folders are renamed structurally
- **Cons / risks:** Needs `wamerican` on the droplet (macOS word list lacks modern words and plurals)
- **Result:** —

## One shared VM instead of one each
- **Context:** Partner could work on his own VM
- **Options:** A) Share one VM, separate user per partner. B) A VM each
- **Chose:** A. Corpus downloaded once, one global mapping, one machine submits
- **Pros:**
  - Half the cost and setup
  - No mapping sync
  - No confusion over which output was submitted
- **Cons / risks:**
  - We compete for CPU. Fix: resize the Droplet, or add a VM later from a volume snapshot
- **Result:** —

## Failed files fall back to a copy of the original
- **Context:** Baseline 292 = input copied unchanged; a broken file likely costs more than a missed name
- **Options:** A) Handler error or failed validation → copy the original. B) Write whatever the handler produced
- **Chose:** A
- **Pros:**
  - A broken file can never reach the corpus
  - The score shouldn't fall below baseline because of a crash
- **Cons / risks:**
  - Names in files that fall back stay unreplaced; watch fallback counts
- **Result:** —

## Length-preserving pseudonyms
- **Context:** SolidWorks / Inventor files are binary; changing string lengths can corrupt them
- **Options:** A) Same byte length and casing as the original. B) Free-form, e.g. Person_0042
- **Chose:** A
- **Pros:**
  - Safe in-place replacement in binary files
  - One scheme for all formats
- **Cons / risks:**
  - Needs a fake-name pool for every length
  - Very short or very long names are awkward
- **Result:** —
