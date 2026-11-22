"""Post-run checks: counts, extensions, object cap, leak scan of paths and a content sample.

python -m deid.verify --out /data/out/attempt-1/corpus --sample 2000
"""
import argparse
import collections
import gzip
import io
import json
import os
import random
import tarfile
import zipfile
from pathlib import Path

from . import config as C
from .handlers import classify
from .matcher import Replacer
from .paths import split_ext


def scan(data: bytes, name: str, R, depth: int = 0) -> collections.Counter:
    """Keys still present, looking inside archives and PDFs the way a checker would."""
    found = collections.Counter()
    kind = classify(name, data[:1024])
    try:
        if kind in ("zip_archive", "zip_container") and depth < 4:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for i in z.infolist():
                    found.update(R.count(i.filename.encode("utf-8", "surrogateescape")))
                    if not i.is_dir() and not i.flag_bits & 1:
                        found.update(scan(z.read(i), i.filename, R, depth + 1))
            return found
        if kind == "tar" and depth < 4:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as t:
                for m in t.getmembers():
                    found.update(R.count(f"{m.name} {m.uname} {m.gname}".encode("utf-8", "surrogateescape")))
                    if m.isfile():
                        found.update(scan(t.extractfile(m).read(), m.name, R, depth + 1))
            return found
        if kind == "gzip" and depth < 4:
            return scan(gzip.decompress(data), name[:-3], R, depth + 1)
        if kind == "pdf":
            import pymupdf
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                meta = " ".join(str(v) for v in (doc.metadata or {}).values())
                found.update(R.count(meta.encode("utf-8", "ignore")))
                found.update(R.count((doc.get_xml_metadata() or "").encode("utf-8", "ignore")))
                text = "\n".join(p.get_text() for p in doc.pages(0, min(len(doc), 20)))
                found.update({"[pdf-text]" + k: v for k, v in R.count(text.encode("utf-8", "ignore")).items()})
            return found
    except Exception:
        pass
    found.update(R.count(data, binary=kind not in ("text", "stl")))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--mapping", default=str(C.PRIVATE / "mapping.json"))
    ap.add_argument("--state", default=None)
    ap.add_argument("--sample", type=int, default=2000)
    a = ap.parse_args()
    out = Path(a.out)
    attempt = out.parent.name if out.name == "corpus" else out.name
    state = Path(a.state or C.PRIVATE / "state" / attempt)
    R = Replacer.load(a.mapping)

    status = {}
    for line in open(state / "status.jsonl", encoding="utf-8"):
        d = json.loads(line)
        status[d["dst"]] = d
    files = [str(p) for p in out.rglob("*") if p.is_file()]
    problems = []
    if len(files) > 400_000:
        problems.append(f"object cap exceeded: {len(files)}")
    tmp = [f for f in files if f.endswith(".deid-tmp")]
    if tmp:
        problems.append(f"{len(tmp)} leftover temp files")
    missing = [d for d in status if not os.path.exists(d)]
    if missing:
        problems.append(f"{len(missing)} outputs missing")
    for dst, d in status.items():
        if split_ext(dst)[1].lower() != split_ext(d["rel"])[1].lower():
            problems.append(f"extension changed: {dst}")

    path_leaks = collections.Counter()
    for f in files:
        rel = os.path.relpath(f, out)
        for k, n in R.count(rel.encode("utf-8", "surrogateescape")).items():
            path_leaks[k] += n

    random.seed(0)
    sample = random.sample(files, min(a.sample, len(files)))
    leaks, leak_files, worst = collections.Counter(), collections.Counter(), []
    for f in sample:
        with open(f, "rb") as fh:
            data = fh.read(64 << 20)
        kind = classify(f, data[:1024])
        found = scan(data, f, R)
        if found:
            st = status.get(f, {}).get("status", "?")
            leak_files[f"{kind}/{st}"] += 1
            worst.append((sum(found.values()), f"{kind}/{st}", os.path.relpath(f, out), sorted(found)[:8]))
            for k, n in found.items():
                leaks[k] += n

    by_status = collections.Counter(d["status"] for d in status.values())
    report = {
        "files": len(files), "status": dict(by_status), "problems": problems[:50],
        "path_leak_keys": len(path_leaks), "path_leaks_top": path_leaks.most_common(30),
        "sampled": len(sample), "content_leak_files_by_kind_status": dict(leak_files),
        "content_leaks_top": leaks.most_common(40),
        "leak_files_top": sorted(worst, reverse=True)[:40],
    }
    json.dump(report, open(state / "verify.json", "w"), indent=1)
    print(json.dumps({k: v for k, v in report.items() if not k.endswith("_top")}, indent=1))
    print(f"full report (contains real identifiers): {state / 'verify.json'}")
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
