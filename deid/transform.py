"""Stage 3: frozen parallel transform. Resumable; never ships an unvalidated file.

python -m deid.transform --out /data/out/attempt-1/corpus --workers 16
Unchanged files and fallbacks are hardlinked from the input (same filesystem).
State (real paths, private) goes to PRIVATE/state/<attempt>/.
"""
import argparse
import collections
import json
import os
import shutil
import signal
import time
from multiprocessing import Pool
from pathlib import Path

from . import config as C
from .handlers import process
from .manifest import load_manifest, present
from .matcher import Replacer
from .paths import rename_rel, split_ext

BIG = 256 << 20
R = None


class Timeout(Exception):
    pass


def _alarm(*_):
    raise Timeout("file timeout")


def _init(mapping_path):
    global R
    R = Replacer.load(mapping_path)
    signal.signal(signal.SIGALRM, _alarm)


def link_or_copy(src, dst):
    if os.path.lexists(dst):
        os.unlink(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _run_group(task):
    src, rel0, dsts = task
    t0 = time.time()
    log, handler, reason, new = [], "", "", None
    try:
        signal.alarm(C.FILE_TIMEOUT_S)
        with open(src, "rb") as f:
            data = f.read()
        new, handler = process(data, rel0, R, 0, log)
        status = "unchanged" if new is None else "changed"
    except Exception as e:
        new, status, reason = None, "fallback", f"{type(e).__name__}: {e}"[:300]
    finally:
        signal.alarm(0)
    first = None
    for rel, dst in dsts:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if new is not None:
            if first is None:
                tmp = dst + ".deid-tmp"
                with open(tmp, "wb") as f:
                    f.write(new)
                os.replace(tmp, dst)
                first = dst
            else:
                link_or_copy(first, dst)
        else:
            link_or_copy(src, dst)
    dt = round(time.time() - t0, 2)
    return [{"rel": rel, "dst": dst, "status": status, "handler": handler, "reason": reason,
             "member_fallbacks": len(log), "secs": dt} for rel, dst in dsts]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(C.MANIFEST))
    ap.add_argument("--input", default=str(C.INPUT))
    ap.add_argument("--out", required=True, help="attempt corpus dir, e.g. /data/out/attempt-1/corpus")
    ap.add_argument("--mapping", default=str(C.PRIVATE / "mapping.json"))
    ap.add_argument("--state", default=None)
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--prefix", default="")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    out = Path(a.out)
    attempt = out.parent.name if out.name == "corpus" else out.name
    state = Path(a.state or C.PRIVATE / "state" / attempt)
    state.mkdir(parents=True, exist_ok=True)
    R0 = Replacer.load(a.mapping)

    rows = [r for r in load_manifest(a.manifest) if r.rel.startswith(a.prefix)]
    found = list(present(rows, a.input))
    if a.limit:
        found = found[: a.limit]
    print(f"transform: {len(rows)} manifest rows, {len(found)} present", flush=True)

    newrel, taken = {}, {}
    for r, _ in found:
        n = rename_rel(r.rel, R0)
        if split_ext(n)[1].lower() != split_ext(r.rel)[1].lower() or n in taken:
            n = r.rel
        if n in taken:
            raise SystemExit(f"path collision on {n}")
        taken[n] = r.rel
        newrel[r.rel] = n
    with open(state / "renames.tsv", "w", encoding="utf-8") as f:
        for o, n in newrel.items():
            if o != n:
                f.write(f"{o}\t{n}\n")

    done = set()
    status_path = state / "status.jsonl"
    if status_path.exists():
        for line in open(status_path, encoding="utf-8"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if os.path.exists(d["dst"]):
                done.add(d["rel"])

    groups = collections.OrderedDict()
    for r, p in found:
        key = (r.md5, r.size) if r.md5 else ("rel", r.rel)
        g = groups.setdefault(key, {"src": str(p), "rel": r.rel, "size": r.size, "dsts": []})
        g["dsts"].append((r.rel, str(out / newrel[r.rel])))
    tasks = [g for g in groups.values() if not all(rel in done for rel, _ in g["dsts"])]
    small = [(g["src"], g["rel"], g["dsts"]) for g in tasks if g["size"] < BIG]
    big = [(g["src"], g["rel"], g["dsts"]) for g in tasks if g["size"] >= BIG]
    print(f"  {len(groups)} content groups, {len(tasks)} to do ({len(big)} big), {len(done)} files already done", flush=True)

    counts = collections.Counter()
    t0 = time.time()
    with open(status_path, "a", encoding="utf-8") as st:
        for batch, nw in ((small, a.workers), (big, max(1, a.workers // 4))):
            if not batch:
                continue
            with Pool(nw, initializer=_init, initargs=(a.mapping,)) as pool:
                for i, res in enumerate(pool.imap_unordered(_run_group, batch, chunksize=4 if nw == a.workers else 1), 1):
                    for d in res:
                        st.write(json.dumps(d) + "\n")
                        counts[d["status"]] += 1
                    if i % 1000 == 0:
                        st.flush()
                        print(f"  {i}/{len(batch)} groups {dict(counts)} {time.time() - t0:.0f}s", flush=True)

    summary = collections.defaultdict(collections.Counter)
    for line in open(status_path, encoding="utf-8"):
        d = json.loads(line)
        summary[os.path.splitext(d["rel"])[1].lower()][d["status"]] += 1
    json.dump({k: dict(v) for k, v in sorted(summary.items())}, open(state / "summary.json", "w"), indent=1)
    print(f"transform done in {time.time() - t0:.0f}s: {dict(counts)} ; state in {state}")


if __name__ == "__main__":
    main()
