"""Which mapping keys hit across many unrelated repos? (generic terms rather than names)

Samples files under INPUT, applies the same text/binary matching as the transform, and
writes PRIVATE/key_spread.tsv: key, repos hit, total hits, example rel.
Usage: python scripts/key_spread.py [--files 40000] [--read-mb 1]
"""
import argparse
import collections
import os
import random
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deid import config as C  # noqa: E402
from deid.batch import group_key  # noqa: E402
from deid.matcher import Replacer  # noqa: E402

R = None
READ = 1 << 20


def _init(mapping, read):
    global R, READ
    R = Replacer.load(mapping)
    READ = read


def _work(rel):
    try:
        with open(os.path.join(C.INPUT, rel), "rb") as f:
            data = f.read(READ)
    except OSError:
        return rel, {}
    binary = b"\x00" in data[:8192]
    return rel, R.count(data, binary=binary)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=40000)
    ap.add_argument("--read-mb", type=float, default=1)
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    a = ap.parse_args()
    rels = []
    for root, _d, files in os.walk(C.INPUT):
        for n in files:
            rels.append(os.path.relpath(os.path.join(root, n), C.INPUT))
    random.Random(0).shuffle(rels)
    rels = rels[: a.files]
    repos = collections.defaultdict(set)
    total = collections.Counter()
    example = {}
    with Pool(a.workers, _init, (str(C.PRIVATE / "mapping.json"), int(a.read_mb * (1 << 20)))) as pool:
        for i, (rel, found) in enumerate(pool.imap_unordered(_work, rels, chunksize=32)):
            g = group_key(rel)
            for k, n in found.items():
                repos[k].add(g)
                total[k] += n
                example.setdefault(k, rel)
            if i % 5000 == 0:
                print(f"{i}/{len(rels)}", flush=True)
    out = C.PRIVATE / "key_spread.tsv"
    with open(out, "w", encoding="utf-8") as f:
        for k in sorted(repos, key=lambda k: (-len(repos[k]), -total[k])):
            f.write(f"{k}\t{len(repos[k])}\t{total[k]}\t{example[k]}\n")
    print(f"{len(repos)} keys hit in {len(rels)} files -> {out}")


if __name__ == "__main__":
    main()
