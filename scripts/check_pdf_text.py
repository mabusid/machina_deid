"""PDF page-text check: pseudonym lands where the name was; other words survive.

python scripts/check_pdf_text.py --n 80   (prefers rotated pages)
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pymupdf  # noqa: E402

from deid import config as C  # noqa: E402
from deid.handlers import process  # noqa: E402
from deid.manifest import load_manifest  # noqa: E402
from deid.matcher import Replacer  # noqa: E402


def words(doc):
    return [set(w[4] for w in p.get_text("words")) for p in doc]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=80)
    a = ap.parse_args()
    R = Replacer.load(C.PRIVATE / "mapping.json")
    rows = [r for r in load_manifest(C.MANIFEST) if r.rel.lower().endswith(".pdf")
            and os.path.exists(os.path.join(C.INPUT, r.rel)) and r.size < 10 << 20]
    random.Random(2).shuffle(rows)
    files = rot = lost_total = placed = misplaced = 0
    for r in rows:
        if files >= a.n:
            break
        data = open(os.path.join(C.INPUT, r.rel), "rb").read()
        try:
            src = pymupdf.open(stream=data, filetype="pdf")
            new, _ = process(data, r.rel, R)
        except Exception:  # noqa: BLE001
            continue
        if new is None:
            continue
        dst = pymupdf.open(stream=new, filetype="pdf")
        changed_pages = [i for i in range(len(src)) if src[i].get_text() != dst[i].get_text()]
        if not changed_pages:
            continue
        files += 1
        for i in changed_pages:
            sp, dp = src[i], dst[i]
            rot += bool(sp.rotation)
            sw, dw = set(w[4] for w in sp.get_text("words")), set(w[4] for w in dp.get_text("words"))
            gone = [w for w in sw - dw if not R.hits(w.encode("utf-8", "ignore"))
                    and len(w) > 2 and any(c.isalpha() for c in w)]
            lost_total += len(gone)
            if gone:
                print(f"lost {gone[:6]} rot={sp.rotation} {r.rel[-60:]} p{i}")
            b = sp.get_text().encode("utf-8", "ignore")
            for s, e, p in R.hits(b)[:5]:
                orig = b[s:e].decode("utf-8", "ignore")
                for rect in sp.search_for(orig)[:2]:
                    box = dp.get_textbox(rect + (-3, -3, 3, 3)).lower()
                    if p[: max(3, len(p) // 2)] in box:
                        placed += 1
                    else:
                        misplaced += 1
                        print(f"misplaced rot={sp.rotation} {orig!r}->{p!r} got {box[:40]!r} {r.rel[-50:]}")
    print(f"files {files}, rotated changed pages {rot}, lost words {lost_total}, "
          f"placed {placed}, misplaced {misplaced}")


if __name__ == "__main__":
    main()
