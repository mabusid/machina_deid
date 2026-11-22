"""Quick handler check on real input: leaks before/after (verify.scan), time, validity.

python scripts/try_handler.py --ext .pdf --n 40
"""
import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deid import config as C  # noqa: E402
from deid.handlers import process  # noqa: E402
from deid.manifest import load_manifest  # noqa: E402
from deid.matcher import Replacer  # noqa: E402
from deid.verify import scan  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ext", default=".pdf")
    ap.add_argument("--n", type=int, default=40)
    a = ap.parse_args()
    R = Replacer.load(C.PRIVATE / "mapping.json")
    S = R.ole_prop if a.ext not in (".pdf",) else R
    rows = [r for r in load_manifest(C.MANIFEST) if r.rel.lower().endswith(a.ext)
            and os.path.exists(os.path.join(C.INPUT, r.rel)) and r.size < 20 << 20]
    random.Random(1).shuffle(rows)
    tot_b = tot_a = 0
    t_all = 0.0
    for r in rows[: a.n]:
        data = open(os.path.join(C.INPUT, r.rel), "rb").read()
        before = scan(data, r.rel, S)
        t = time.time()
        try:
            new, kind = process(data, r.rel, R)
        except Exception as e:  # noqa: BLE001
            print("ERR", type(e).__name__, str(e)[:80], r.rel[-60:])
            continue
        dt = time.time() - t
        t_all += dt
        after = scan(new if new is not None else data, r.rel, S)
        nb, na = sum(before.values()), sum(after.values())
        tot_b += nb
        tot_a += na
        if nb or na:
            print(f"{nb:4d} -> {na:4d}  {dt:5.2f}s {kind:8s} {r.rel[-70:]}"
                  + (f"  left: {list(after)[:4]}" if na else ""))
    print(f"total leaks {tot_b} -> {tot_a}; {t_all:.1f}s for {min(a.n, len(rows))} files")


if __name__ == "__main__":
    main()
