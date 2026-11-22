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
