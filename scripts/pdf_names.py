"""Harvest person names from PDF page text (title blocks) and extend the frozen mapping.

Candidates: name-shaped strings on, or within a few lines after, a title-block label
(Drawn/Checked/Approved/Designer/Author/..., German/Spanish/French variants), plus
"by: Name" forms. Existing keys/pseudonyms are never changed: the pseudonymizer is
pre-seeded with every token mapping already in mapping.json.

python scripts/pdf_names.py --rels /root/private/attempt2-rels.txt [--dry]
"""
import argparse
import collections
import json
import os
import re
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deid import config as C  # noqa: E402
from deid.allowlist import ALLOW, is_common  # noqa: E402
from deid.pseudo import FIRST, Pseudonymizer, is_word, tokens  # noqa: E402

LABEL = re.compile(r"(?i)(drawn|designe[dr]|checked|chk|approved|appr|author|engineer|created|"
                   r"made by|drafte[dr]|draftsman|erstellt|gezeichnet|gepr|bearb|kontrolliert|"
                   r"konstrukt|dibuj|revisad|aprobad|dise[nñ]|dessin|v[ée]rifi|approuv|"
                   r"\bname\b|nombre|\bnom\b|autor|\bby\b)")
NAME2 = re.compile(r"\b([A-Z][a-z]+|[A-Z]{2,})[ ]+([A-Z][a-z]{2,}(?:-[A-Z][a-z]+)?|[A-Z]{3,})\b")
INIT = re.compile(r"\b([A-Z])\.[ ]?([A-Z][a-z]{2,}|[A-Z]{3,})\b")
BY = re.compile(r"(?i:\bby)[: ]+([A-Z][a-z]{2,})\b")
STOP = {w.lower() for w in """Drawn Checked Approved Designer Designed Author Engineer Created
Name Date Scale Sheet Title Material Weight Mass Rev Revision Size Drawing Part Number Qty
Quantity Finish Tolerance Tolerances General Description Document Status Type Release Initial
Unless Otherwise Specified Dimensions Third First Angle Projection Signature Approval Nombre
Fecha Escala Plano Datum Gezeichnet Erstellt Kontrolliert Norm Masstab Blatt Werkstoff Gewicht
Benennung Zeichnungsnummer Dibujado Revisado Aprobado Dessine Verifie Approuve Echelle Format
Solid Edge Works Inventor Autodesk Academic Copy Student Version Kg Mm Inch Iso Din Ansi
Third Angle The For And With From Only All Rights Reserved Company Inc Ltd Gmbh Sie Und Von
Der Die Das Ein Eine Zur Zum Mit Bei Technische Referenz British Cern Ohl Sub-Assembly Assembly
Impeller Ostschweizer Ost Croft Moule Verrine Darachbeg Iniciaomo Cienttfica""".split()}
DROP = set()
if os.path.exists(C.PRIVATE / "pdf_names_drop.txt"):
    DROP = {l.strip().lower() for l in open(C.PRIVATE / "pdf_names_drop.txt", encoding="utf-8") if l.strip()}
FIRSTS = {f.lower() for f in FIRST}


def ok_first(t):
    t = t.lower()
    return t not in STOP and (t in FIRSTS or not is_common(t)) and t not in ALLOW


def ok_last(t):
    t = t.lower()
    return len(t) >= 3 and t not in STOP and not is_common(t) and t not in ALLOW


def candidates(text):
    out = set()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, l in enumerate(lines):
        if len(l) > 80 or not LABEL.search(l):
            continue
        for s in [l] + lines[i + 1:i + 6]:
            if len(s) > 60 or not s.isascii():
                continue
            for a, b in NAME2.findall(s):
                if a.isupper() and b.isupper() and a.lower() not in FIRSTS:
                    continue
                if ok_first(a) and ok_last(b):
                    out.add(f"{a} {b}")
            for a, b in INIT.findall(s):
                if ok_last(b):
                    out.add(f"{a}. {b}")
            for b in BY.findall(s):
                if ok_last(b):
                    out.add(b)
    return out


def _work(path):
    import pymupdf
    try:
        doc = pymupdf.open(path)
        if doc.needs_pass:
            return set()
        found = set()
        for page in doc.pages(0, min(len(doc), 6)):
            found |= candidates(page.get_text())
        return found
    except Exception:  # noqa: BLE001
        return set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rels", required=True)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    a = ap.parse_args()
    rels = [l.rstrip("\n") for l in open(a.rels, encoding="utf-8") if l.lower().rstrip().endswith(".pdf")]
    paths = [os.path.join(C.INPUT, r) for r in rels if os.path.exists(os.path.join(C.INPUT, r))]
    cnt = collections.Counter()
    with Pool(a.workers) as pool:
        for s in pool.imap_unordered(_work, paths, chunksize=16):
            cnt.update(s)
    for d in [k for k in cnt if k.lower() in DROP]:
        del cnt[d]
    print(f"{len(paths)} PDFs, {len(cnt)} candidate names")
    with open(C.PRIVATE / "pdf_names.tsv", "w", encoding="utf-8") as f:
        for k, n in cnt.most_common():
            f.write(f"{n}\t{k}\n")
    if a.dry:
        return

    mp = C.PRIVATE / "mapping.json"
    m = json.load(open(mp, encoding="utf-8"))
    keys = m["keys"]
    secret = bytes.fromhex(open(C.PRIVATE / "secret.key").read().strip())
    P = Pseudonymizer(secret, reserved={t for v in list(cnt) + list(keys) for t in tokens(v.lower()) if is_word(t)})
    for k, v in keys.items():
        for tk, tv in zip(tokens(k), tokens(v)):
            if is_word(tk) and tk != tv and tk not in P.map:
                P.map[tk] = tv
                P.used.add(tv)
    added = {}
    for name, _n in sorted(cnt.items(), key=lambda t: (-t[1], t[0])):
        low = name.lower()
        variants = {low}
        toks = [t for t in tokens(low) if is_word(t)]
        if len(toks) == 2:
            variants |= {f"{toks[0][0]}. {toks[1]}", f"{toks[0][0]}.{toks[1]}"}
            if len(toks[1]) >= 5:
                variants.add(toks[1])
        for var in sorted(variants, key=len, reverse=True):
            if var in keys or var in added or len(var) < 4:
                continue
            if " " not in var and "." not in var and (is_common(var) or len(var) < 5):
                continue
            words = [t for t in tokens(var) if is_word(t)]
            p = P.phrase(var, lambda t: len(t) > 1,
                         lambda i, t: "last" if t == words[-1] else "first")
            if len(p) == len(var) and p != var:
                added[var] = p
    keys.update(added)
    json.dump(m, open(mp, "w", encoding="utf-8"), indent=0, sort_keys=True)
    print(f"added {len(added)} keys; mapping now {len(keys)}")
    print(sorted(added)[:40])


if __name__ == "__main__":
    main()
