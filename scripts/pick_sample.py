"""Stratified dev sample: N files per extension, spread across sources/repos, size-capped.

python scripts/pick_sample.py --manifest /data/manifest.tsv --dest /data/sample --per-ext 20
The sample keeps the manifest's relative paths, so all pipeline stages run on it
with --input /data/sample. Writes <dest>/sample-manifest.tsv (private: real paths).
"""
import argparse
import collections
import os
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from deid.config import BASE_URL  # noqa: E402
from deid.manifest import load_manifest  # noqa: E402
from deid.paths import ext_of  # noqa: E402


def group_of(rel):
    p = rel.split("/")
    return "/".join(p[:3])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--per-ext", type=int, default=20)
    ap.add_argument("--max-mb", type=float, default=40)
    ap.add_argument("--min-count", type=int, default=5, help="skip extensions rarer than this")
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    rows = load_manifest(a.manifest)
    by_ext = collections.defaultdict(list)
    for r in rows:
        if r.size <= a.max_mb * 1e6:
            by_ext[ext_of(r.rel)].append(r)
    rnd = random.Random(a.seed)
    picked = []
    for ext, rs in sorted(by_ext.items()):
        if len(rs) < a.min_count:
            continue
        rnd.shuffle(rs)
        seen, chosen = collections.Counter(), []
        for r in rs:  # round-robin over repos/sources for diversity
            if seen[group_of(r.rel)] < 2:
                chosen.append(r)
                seen[group_of(r.rel)] += 1
            if len(chosen) >= a.per_ext:
                break
        picked += chosen
    for r in rows:  # always include the top-level archives
        if r.rel.startswith("archives/") and r.size < 200e6 and r not in picked:
            picked.append(r)
    print(f"{len(picked)} files, {sum(r.size for r in picked) / 1e9:.2f} GB, {len(by_ext)} extensions")

    os.makedirs(a.dest, exist_ok=True)
    with open(os.path.join(a.dest, "sample-manifest.tsv"), "w", encoding="utf-8") as f:
        f.write("# path\tbytes\tmd5\turl path\n")
        for r in picked:
            f.write(f"{r.rel}\t{r.size}\t{r.md5}\t{r.url}\n")

    def fetch(r):
        dst = os.path.join(a.dest, r.rel)
        if os.path.exists(dst) and os.path.getsize(dst) == r.size:
            return 0
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        url = BASE_URL + r.url  # manifest url column is already percent-encoded
        tmp = dst + ".part"
        subprocess.run(["curl", "-fsSL", "--retry", "3", "-o", tmp, url], check=True)
        os.replace(tmp, dst)
        return 1

    errs = 0
    with ThreadPoolExecutor(a.jobs) as ex:
        for r, fut in zip(picked, [ex.submit(fetch, r) for r in picked]):
            try:
                fut.result()
            except Exception as e:
                errs += 1
                print("ERR", r.rel[:80], e)
    print(f"done, {errs} errors")


if __name__ == "__main__":
    main()
