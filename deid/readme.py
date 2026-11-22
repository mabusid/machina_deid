"""Generate attempt README.txt from run state (final paths only, no original identifiers).

python -m deid.readme --out /data/out/attempt-1/corpus > /data/out/attempt-1/README.txt
"""
import argparse
import collections
import json
import os
from pathlib import Path

from . import config as C

TEMPLATE = """\
Machina CAD de-identification - {attempt}
Scorer version: machina-deid-1

HOW TO RUN (Ubuntu 24.04, Python 3.12, case-sensitive filesystem)
  apt install -y python3-venv wamerican
  python3 -m venv .venv && . .venv/bin/activate && pip install -r code/requirements.lock.txt
  export DEID_DATA=/data             # input in $DEID_DATA/input, manifest at $DEID_DATA/manifest.tsv
  python -m deid.harvest  --workers 16      # stage 1: identity candidates -> private/harvest.json
  python -m deid.resolve                    # stage 2: frozen mapping      -> private/mapping.json
  python -m deid.transform --out /data/out/{attempt}/corpus --workers 16
  python -m deid.verify    --out /data/out/{attempt}/corpus
  The private/ directory (mapping, secret key, run state) is not part of this submission.

METHOD
  - Identities are harvested from paths (repository owners and names, catalog projects, source
    websites), STEP/IGES/DXF headers, OLE property sets, PDF/XMP metadata, FreeCAD/3MF
    metadata, user-profile paths, e-mail addresses, copyright lines and title-block labels.
  - Each identity gets one deterministic pseudonym (keyed hash). Pseudonyms keep the byte length
    and letter case of the original, so 'J. Smith', 'jsmith' and 'SMITH' stay consistent and
    binary files keep their structure.
  - File and folder names are rewritten with the same mapping; extensions, depth and generic
    folders are kept. References inside files use the same mapping, so renamed links still match.
  - Text formats: whole-file length-preserving replacement (base64 payloads untouched).
  - Native binaries (SolidWorks, Inventor, Creo, Parasolid, JT, ...): edits only inside long
    printable ASCII / UTF-16LE strings; OLE directory and stream sizes are verified unchanged.
  - PDF: document info, XMP, annotation/outline strings and embedded files; page count verified.
  - Archives (zip, tar, gz) and ZIP-based containers (FCStd, 3MF, F3D) are processed recursively.
  - Images: PNG text chunks, JPEG APP/COM segments, TIFF strings.
  - Any handler error or failed validation keeps the original file unchanged (never dropped).

RESULTS
  Files in corpus: {files}
  {status_line}

EXCEPTIONS AND LIMITATIONS
{exceptions}

FILES KEPT UNCHANGED BECAUSE OF ERRORS (final paths; first 300)
{fallbacks}
"""

LIMITS = """\
  - DWG, RAR, 7z, Unix-compress (.Z), GIF/BMP/WebP files are copied unchanged (no safe writer).
  - Compressed streams inside native CAD files and visible text rendered in PDF pages or
    images (including logos) are not rewritten in this attempt.
  - Non-ASCII names are not pseudonymized in this attempt.
  - Byte-identical duplicates in the input are processed once and kept at every path."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--state", default=None)
    a = ap.parse_args()
    out = Path(a.out)
    attempt = out.parent.name if out.name == "corpus" else out.name
    state = Path(a.state or C.PRIVATE / "state" / attempt)
    st = [json.loads(l) for l in open(state / "status.jsonl", encoding="utf-8")]
    last = {d["rel"]: d for d in st}
    counts = collections.Counter(d["status"] for d in last.values())
    empty = [d for d in last.values() if d.get("size") == 0 or
             (d.get("size") is None and os.path.exists(d["dst"]) and os.path.getsize(d["dst"]) == 0)]
    fb = [d for d in last.values() if d["status"] == "fallback"]
    exc = LIMITS + f"\n  - {len(empty)} input files are empty (0 bytes); kept as empty files:\n"
    exc += "\n".join("      " + os.path.relpath(d["dst"], out) for d in empty[:100])
    reasons = collections.Counter(d["reason"].split(":")[0] for d in fb)
    exc += "\n  - Fallback reasons: " + ", ".join(f"{k} x{v}" for k, v in reasons.most_common(10))
    print(TEMPLATE.format(
        attempt=attempt, files=len(last),
        status_line=", ".join(f"{k}: {v}" for k, v in counts.most_common()),
        exceptions=exc,
        fallbacks="\n".join("  " + os.path.relpath(d["dst"], out) for d in fb[:300]) or "  (none)",
    ))


if __name__ == "__main__":
    main()
