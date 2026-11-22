"""Space-bounded runner for disks smaller than the input (e.g. a 100 GB volume).

The corpus is cut into slices of whole repositories (manifest order). Each slice is
downloaded, processed and (for transform) uploaded, then removed when space is needed.
The earliest slices stay on disk so later passes re-download as little as possible.

  python -m deid.batch harvest
  python -m deid.batch transform --attempt 1 --upload-cmd "python3 /data/upload.py ..."

Both are resumable: finished slices are recorded under PRIVATE/.
"""
import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
import time
from multiprocessing import Pool
from pathlib import Path

from . import config as C
from .harvest import _work, path_entities
from .manifest import load_manifest


def group_key(rel: str) -> str:
    p = rel.split("/")
    return "/".join(p[:3]) if p[0] == "sources" else "/".join(p[:2])


def make_slices(rows, slice_gb):
    groups = collections.OrderedDict()
    for r in rows:
        groups.setdefault(group_key(r.rel), []).append(r)
    slices, cur, size = [], [], 0
    for g in groups.values():
        gs = sum(r.size for r in g)
        if cur and size + gs > slice_gb * 1e9:
            slices.append(cur)
            cur, size = [], 0
        cur += g
        size += gs
    if cur:
        slices.append(cur)
    return slices


def free_gb(path) -> float:
    return shutil.disk_usage(path).free / 1e9


def _present(r, dest: Path) -> bool:
    p = dest / r.rel
    try:
        return p.stat().st_size == r.size
    except OSError:
        return False


def missing_bytes(rows, dest) -> int:
    return sum(r.size for r in rows if not _present(r, dest))


def resident_bytes(rows, dest) -> int:
    return sum(r.size for r in rows if _present(r, dest))


def download(rows, dest: Path, jobs: int):
    for attempt in range(3):
        todo = []
        for r in rows:
            p = dest / r.rel
            if r.size == 0:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.touch()
                continue
            if _present(r, dest):
                continue
            if p.is_file() and p.stat().st_size > r.size:
                p.unlink()
            todo.append(r)
        if not todo:
            return []
        lst = dest / ".batch-aria2.txt"
        with open(lst, "w", encoding="utf-8") as f:
            for r in todo:
                f.write(f"{C.BASE_URL}{r.url}\n  dir={dest}\n  out={r.rel}\n")
        print(f"  downloading {len(todo)} files, {sum(r.size for r in todo) / 1e9:.1f} GB (try {attempt + 1})", flush=True)
        subprocess.run(["aria2c", "-i", str(lst), "-j", str(jobs), "-x", "1", "-c",
                        "--auto-file-renaming=false", "--allow-overwrite=true", "--max-tries=10",
                        "--retry-wait=5", "--console-log-level=error", "--summary-interval=0",
                        "--download-result=hide", "--file-allocation=none"], check=False)
    missing = [r for r in rows if not _present(r, dest)]
    if missing:
        print(f"  WARNING: {len(missing)} files still missing after 3 tries", flush=True)
    return missing


def delete_inputs(rows, dest: Path):
    dirs = set()
    for r in rows:
        p = dest / r.rel
        if p.exists():
            p.unlink()
            dirs.add(p.parent)
    for d in sorted(dirs, key=lambda x: -len(str(x))):
        try:
            os.removedirs(d)
        except OSError:
            pass


def ensure_space(slices, i, need_gb, dest: Path, done: set):
    """Free space by evicting other slices' inputs: finished ones first, then later ones,
    latest index first, so the earliest slices stay resident for the next pass."""
    order = sorted((j for j in done if j != i), reverse=True)
    order += sorted((j for j in range(len(slices)) if j not in done and j != i), reverse=True)
    for j in order:
        if free_gb(dest) >= need_gb:
            return
        if resident_bytes(slices[j], dest):
            print(f"  evicting input of slice {j + 1} to free space", flush=True)
            delete_inputs(slices[j], dest)
    if free_gb(dest) < need_gb:
        print(f"  WARNING: only {free_gb(dest):.0f} GB free, wanted {need_gb:.0f} GB", flush=True)


def _common(ap):
    ap.add_argument("--manifest", default=str(C.MANIFEST))
    ap.add_argument("--input", default=str(C.INPUT))
    ap.add_argument("--slice-gb", type=float, default=12)
    ap.add_argument("--reserve-gb", type=float, default=6)
    ap.add_argument("--jobs", type=int, default=32)
    ap.add_argument("--workers", type=int, default=os.cpu_count())


def cmd_harvest(a):
    dest = Path(a.input)
    dest.mkdir(parents=True, exist_ok=True)
    rows = load_manifest(a.manifest)
    slices = make_slices(rows, a.slice_gb)
    st = C.PRIVATE / "batch"
    st.mkdir(parents=True, exist_ok=True)
    done = {i for i in range(len(slices)) if (st / f"harvest-{i:03d}.json").exists()}
    t0 = time.time()
    for i, sl in enumerate(slices):
        if i in done:
            continue
        gb = sum(r.size for r in sl) / 1e9
        print(f"[harvest] slice {i + 1}/{len(slices)}: {len(sl)} files, {gb:.1f} GB, "
              f"free {free_gb(dest):.0f} GB, {time.time() - t0:.0f}s", flush=True)
        ensure_space(slices, i, missing_bytes(sl, dest) / 1e9 + a.reserve_gb, dest, done)
        missing = download(sl, dest, a.jobs)
        seen, todo = set(), []
        for r in sl:
            key = (r.md5, r.size) if r.md5 else r.rel
            if key in seen or not _present(r, dest):
                continue
            seen.add(key)
            todo.append((str(dest / r.rel), r.rel))
        counts, examples = collections.Counter(), {}
        with Pool(a.workers) as pool:
            for rel, c in pool.imap_unordered(_work, todo, chunksize=8):
                for kv, n in c.items():
                    counts[kv] += n
                    examples.setdefault(f"{kv[0]}\t{kv[1]}", rel)
        out = st / f"harvest-{i:03d}.json"
        with open(str(out) + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"counts": {f"{k}\t{v}": n for (k, v), n in counts.items()},
                       "examples": examples, "missing": [r.rel for r in missing]}, f)
        os.replace(str(out) + ".tmp", out)
        done.add(i)

    counts, examples = collections.Counter(), {}
    for r in rows:
        for k, v in path_entities(r.rel):
            counts[f"{k}\t{v}"] += 1
            examples.setdefault(f"{k}\t{v}", r.rel)
    for i in range(len(slices)):
        h = json.load(open(st / f"harvest-{i:03d}.json", encoding="utf-8"))
        for kv, n in h["counts"].items():
            counts[kv] += n
        for kv, ex in h["examples"].items():
            examples.setdefault(kv, ex)
    with open(C.PRIVATE / "harvest.json", "w", encoding="utf-8") as f:
        json.dump({"counts": dict(counts), "examples": examples}, f)
    print(f"[harvest] merged {len(slices)} slices -> {C.PRIVATE / 'harvest.json'}")


def cmd_transform(a):
    dest = Path(a.input)
    rows = load_manifest(a.manifest)
    slices = make_slices(rows, a.slice_gb)
    att = C.OUT / f"attempt-{a.attempt}"
    corpus = att / "corpus"
    state = C.PRIVATE / "state" / f"attempt-{a.attempt}"
    state.mkdir(parents=True, exist_ok=True)
    done_f = state / "batch_done.txt"
    done = {int(x) for x in open(done_f).read().split()} if done_f.exists() else set()
    repo = Path(__file__).resolve().parent.parent

    if not (att / "code").exists():
        (att / "code").mkdir(parents=True)
        subprocess.run(f"git -C {repo} archive HEAD | tar -x -C {att / 'code'}", shell=True, check=True)
        subprocess.run(f"{sys.executable} -m pip freeze > {att / 'code' / 'requirements.lock.txt'}",
                       shell=True, check=True)

    t0 = time.time()
    for i, sl in enumerate(slices):
        if i in done:
            continue
        gb = sum(r.size for r in sl) / 1e9
        print(f"[transform] slice {i + 1}/{len(slices)}: {len(sl)} files, {gb:.1f} GB, "
              f"free {free_gb(dest):.0f} GB, {time.time() - t0:.0f}s", flush=True)
        # room for missing input + this slice's rewritten output (unchanged files are hardlinks)
        ensure_space(slices, i, missing_bytes(sl, dest) / 1e9 + gb + a.reserve_gb, dest, done)
        download(sl, dest, a.jobs)
        rels = state / "slice-rels.txt"
        rels.write_text("\n".join(r.rel for r in sl), encoding="utf-8")
        subprocess.run([sys.executable, "-m", "deid.transform", "--manifest", a.manifest,
                        "--input", str(dest), "--out", str(corpus), "--rels-file", str(rels),
                        "--workers", str(a.workers)], cwd=repo, check=True)
        if a.upload_cmd:
            print("  uploading slice", flush=True)
            subprocess.run(a.upload_cmd, shell=True, cwd=att, check=True)
            shutil.rmtree(corpus, ignore_errors=True)
        with open(done_f, "a") as f:
            f.write(f"{i}\n")
        done.add(i)

    readme = att / "README.txt"
    with open(readme, "w", encoding="utf-8") as f:
        subprocess.run([sys.executable, "-m", "deid.readme", "--out", str(corpus)],
                       cwd=repo, stdout=f, check=True)
    print(f"[transform] all {len(slices)} slices done in {time.time() - t0:.0f}s; README at {readme}")
    if a.upload_cmd:
        corpus.mkdir(parents=True, exist_ok=True)
        subprocess.run(a.upload_cmd + " --readme README.txt", shell=True, cwd=att, check=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("harvest")
    _common(h)
    t = sub.add_parser("transform")
    _common(t)
    t.add_argument("--attempt", type=int, required=True)
    t.add_argument("--upload-cmd", default="", help="shell command run in attempt-N/ after each slice")
    a = ap.parse_args()
    cmd_harvest(a) if a.cmd == "harvest" else cmd_transform(a)


if __name__ == "__main__":
    main()
