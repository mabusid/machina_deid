"""Stage 1: collect identity candidates (read-only, parallel).

python -m deid.harvest --workers 16
Writes PRIVATE/harvest.json: {"counts": {"kind\\tvalue": n}, "examples": {...}}
"""
import argparse
import collections
import gzip
import io
import json
import os
import tarfile
import time
from multiprocessing import Pool

from . import config as C
from . import extract as X
from .handlers import classify
from .manifest import load_manifest, unique_present


def path_entities(rel: str):
    parts = rel.split("/")
    if len(parts) > 2 and parts[0] == "sources":
        src, seg = parts[1], parts[2]
        if src in ("github", "gitlab"):
            bits = seg.split("__")
            if bits and "." in bits[0]:
                yield "host", bits[0].lower()
                bits = bits[1:]
            if bits:
                yield "owner", bits[0]
            if len(bits) > 1:
                yield "repo", bits[1]
        elif src == "catalog":
            yield "project", seg
        elif src == "web":
            yield "host", seg.lower()
            for p in parts[3:-1]:
                if "-" in p and any(w in p.lower() for w in ("llc", "inc", "mfg", "corp", "gmbh", "ltd")):
                    yield "org_slug", p
    elif parts[0] == "archives" and len(parts) > 1:
        bits = parts[1].split("__")
        if len(bits) >= 2:
            yield "owner", bits[0]
            yield "repo", bits[1].removesuffix(".zip")


def harvest_blob(data: bytes, name: str, depth: int = 0):
    kind = classify(name, data[:1024])
    blob = data
    if kind in ("binary", "ole", "image", "copy", "stl"):
        blob = X.binary_strings(data)
    if kind not in ("zip_archive", "zip_container", "tar", "gzip"):
        yield from X.regex_entities(blob)
    ext = name.lower()
    try:
        if kind == "text":
            if ext.endswith((".step", ".stp", ".p21")) or data[:13] == b"ISO-10303-21;":
                yield from X.step_header(data)
            elif ext.endswith((".igs", ".iges")):
                yield from X.iges_global(data)
            elif ext.endswith(".dxf"):
                yield from X.dxf_header(data)
        elif kind == "ole":
            yield from X.ole_props(data)
        elif kind == "pdf":
            yield from X.pdf_meta(data)
        elif kind in ("zip_archive", "zip_container") and depth < C.MAX_ARCHIVE_DEPTH:
            for mname, mhead in X.zip_members(data):
                yield from X.regex_entities(mname.encode("utf-8", "ignore"))
                if mhead:
                    yield from X.container_meta(mhead)
                    yield from harvest_blob(mhead, mname, depth + 1)
        elif kind == "tar" and depth < C.MAX_ARCHIVE_DEPTH:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as t:
                for m in t.getmembers():
                    for u in (m.uname, m.gname):
                        if u:
                            yield "username", u
                    if m.isfile():
                        yield from harvest_blob(t.extractfile(m).read(C.HARVEST_HEAD_BIN), m.name, depth + 1)
        elif kind == "gzip" and depth < C.MAX_ARCHIVE_DEPTH:
            inner = gzip.GzipFile(fileobj=io.BytesIO(data)).read(C.HARVEST_HEAD_BIN)
            yield from harvest_blob(inner, name[:-3] if ext.endswith(".gz") else name, depth + 1)
    except Exception as e:
        yield "_error", f"{kind}:{type(e).__name__}"


def _work(path_rel):
    path, rel = path_rel
    c = collections.Counter()
    try:
        kind = classify(rel, open(path, "rb").read(1024))
        if kind in ("ole", "pdf", "zip_archive", "zip_container", "tar", "gzip"):
            data = open(path, "rb").read()
        else:
            head = C.HARVEST_HEAD_TEXT if kind == "text" else C.HARVEST_HEAD_BIN
            with open(path, "rb") as f:
                data = f.read(head)
        for k, v in harvest_blob(data, rel):
            v = " ".join(str(v).split())
            if v and len(v) <= 200:
                c[(k, v)] += 1
    except Exception as e:
        c[("_error", type(e).__name__)] += 1
    return rel, c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(C.MANIFEST))
    ap.add_argument("--input", default=str(C.INPUT))
    ap.add_argument("--out", default=str(C.PRIVATE / "harvest.json"))
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    rows = load_manifest(a.manifest)
    counts = collections.Counter()
    examples = {}
    for r in rows:
        for k, v in path_entities(r.rel):
            counts[(k, v)] += 1
            examples.setdefault(f"{k}\t{v}", r.rel)

    todo = [(str(p), rel) for rel, p in unique_present(rows, a.input)]
    if a.limit:
        todo = todo[: a.limit]
    print(f"harvest: {len(rows)} manifest rows, {len(todo)} unique files present", flush=True)
    t0 = time.time()
    with Pool(a.workers) as pool:
        for i, (rel, c) in enumerate(pool.imap_unordered(_work, todo, chunksize=8), 1):
            for kv, n in c.items():
                counts[kv] += n
                examples.setdefault(f"{kv[0]}\t{kv[1]}", rel)
            if i % 2000 == 0:
                print(f"  {i}/{len(todo)} files, {len(counts)} candidates, {time.time() - t0:.0f}s", flush=True)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"counts": {f"{k}\t{v}": n for (k, v), n in counts.items()}, "examples": examples}, f)
    kinds = collections.Counter(k for k, _ in counts)
    print("harvest done:", dict(kinds.most_common()), f"-> {a.out}")


if __name__ == "__main__":
    main()
