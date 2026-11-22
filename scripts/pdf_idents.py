"""Add PDF-text emails, person names and company phrases to the frozen mapping.

Existing keys and pseudonyms are kept: the pseudonymizer is pre-seeded from mapping.json.
Only full phrases are added for companies (never bare common words). Person names must be
two uncommon words, so dictionary words like "stainless steel" are not keys.

python scripts/pdf_idents.py --rels /root/private/attempt3-rels.txt
"""
import argparse
import collections
import json
import os
import re
import sys
from multiprocessing import Pool

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deid import config as C
from deid.allowlist import ALLOW, is_common
from deid.pseudo import Pseudonymizer, is_word, tokens
from deid.resolve import FILE_TLDS, PUBLIC_MAIL, TLD_LIKE, TLDS, Builder

NAME = re.compile(r"\b([A-Z][a-z]{2,}|[A-Z]\.)[ ]+([A-Z][a-z]{2,})\b")
LASTF = re.compile(r"\b([A-Z][a-z]{2,}),[ ]+([A-Z][a-z]{2,})\b")
EM = re.compile(r"\b[A-Za-z0-9._%+\-]{2,40}@[A-Za-z0-9.\-]{2,50}\.[A-Za-z]{2,12}\b")
ORG = re.compile(r"\b([A-Z][A-Za-z&'.-]{2,}(?:[ ]+[A-Z][A-Za-z&'.-]{2,}){1,4})[ ]+"
                 r"(?:Inc|LLC|L\.L\.C|Ltd|GmbH|Corp|AG|B\.V|N\.V|Pty|PLC)\b")
MATERIAL = {"steel", "stainless", "aluminum", "aluminium", "plastic", "brass", "bronze",
            "copper", "rubber", "titanium", "nylon", "silicone", "acetal", "acrylic"}


def ok_word(w):
    return len(w) >= 4 and w.isalpha() and not is_common(w) and w.lower() not in ALLOW


def _work(rel):
    path = os.path.join(C.INPUT, rel)
    names, emails, orgs = set(), set(), set()
    try:
        doc = pymupdf.open(path)
        if doc.needs_pass:
            return names, emails, orgs
        for i in range(min(len(doc), 6)):
            t = doc[i].get_text()
            for a, b in NAME.findall(t):
                if a.endswith("."):
                    if ok_word(b):
                        names.add(f"{a[0]}. {b}")
                elif ok_word(a) and ok_word(b):
                    names.add(f"{a} {b}")
            for a, b in LASTF.findall(t):
                if ok_word(a) and ok_word(b):
                    names.add(f"{a}, {b}")
            for m in EM.findall(t):
                emails.add(m.lower())
            for m in ORG.findall(t):
                words = [w for w in re.split(r"[^A-Za-z]+", m) if w]
                low = {w.lower() for w in words}
                if len(words) >= 2 and not (low & MATERIAL) and not low <= ALLOW:
                    orgs.add(" ".join(words))
    except Exception:  # noqa: BLE001
        pass
    return names, emails, orgs


def seed(P, keys):
    for k, v in keys.items():
        kt, vt = tokens(k), tokens(v)
        if len(kt) != len(vt):
            continue
        for tk, tv in zip(kt, vt):
            if is_word(tk) and is_word(tv) and tk not in P.map:
                P.map[tk] = tv
                P.used.add(tv)


def add_email(B, P, v):
    """Full address, plus domain labels of 5+ letters. No 3-letter domain fragments."""
    local, _, domain = v.lower().partition("@")
    labels = domain.split(".")
    if len(labels) < 2 or labels[-1] in FILE_TLDS or labels[-1] not in TLDS:
        return
    if len(local) < 2 or not re.search(r"[a-z]{2}", local):
        return
    public = any(lb in PUBLIC_MAIL for lb in labels[:-1])
    pl = P.phrase(local, lambda t: t not in ALLOW)
    pd = domain if public else ".".join(
        lb if lb in TLD_LIKE else P.phrase(lb, lambda t: True) for lb in labels)
    B.add(v.lower(), pl + "@" + pd)
    if not public:
        for lb in labels:
            if lb not in TLD_LIKE and len(lb) >= 5 and not is_common(lb):
                B.add(lb, P.phrase(lb, lambda t: True))
    parts = [t for t in tokens(local) if is_word(t)]
    if len(parts) == 1 and ok_word(parts[0]):
        B.add(local, pl)
    elif len(parts) >= 2 and len(local) >= 5:
        B.add(local, pl)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rels", required=True)
    a = ap.parse_args()
    rels = [l.rstrip("\n") for l in open(a.rels, encoding="utf-8") if l.lower().rstrip().endswith(".pdf")]
    nc, ec, oc = collections.Counter(), collections.Counter(), collections.Counter()
    with Pool(os.cpu_count() or 2) as pool:
        for names, emails, orgs in pool.imap_unordered(_work, rels, chunksize=8):
            nc.update(names)
            ec.update(emails)
            oc.update(orgs)
    print(f"candidates names {len(nc)} emails {len(ec)} orgs {len(oc)}", flush=True)
    print("NAMES", nc.most_common(25), flush=True)
    print("EMAILS", ec.most_common(15), flush=True)
    print("ORGS", oc.most_common(15), flush=True)
    if nc["Marcos Cerezo"] < 100 or ec["mbokj@mek.dtu.dk"] < 50:
        raise SystemExit("scan missed known repeated identities; mapping not changed")

    mp = C.PRIVATE / "mapping.json"
    m = json.load(open(mp, encoding="utf-8"))
    keys = m["keys"]
    before = dict(keys)
    exclude = set()
    for fn in ("exclude.txt", "pdf_names_drop.txt"):
        p = C.PRIVATE / fn
        if p.exists():
            exclude |= {l.strip().lower() for l in open(p, encoding="utf-8") if l.strip() and not l.startswith("#")}
    reserved = {t.lower() for s in list(nc) + list(ec) + list(oc) + list(keys)
                for t in tokens(s) if is_word(t)}
    secret = bytes.fromhex(open(C.PRIVATE / "secret.key").read().strip())
    P = Pseudonymizer(secret, reserved=reserved)
    seed(P, keys)
    B = Builder(P, exclude)
    B.keys = dict(keys)
    for name, _n in sorted(nc.items(), key=lambda t: (-len(t[0]), -t[1])):
        B.person(name)
    for email, _n in ec.most_common():
        add_email(B, P, email)
    for org, _n in oc.most_common():
        low = org.lower()
        pseudo = P.phrase(low, lambda t: is_word(t) and t not in ALLOW)
        if pseudo != low and len(pseudo) == len(low):
            B.add(low, pseudo)
    added = {k: v for k, v in B.keys.items() if k not in before}
    # a single new token that is a dictionary word never becomes a key
    # Bare 3-5 letter tokens from this pass are foreign function words and abbreviations
    # ("eine", "glas", "gelb"). Phrases, emails and initials stay; longer bare surnames stay.
    bare_drop = {"alumini", "russia", "kazan", "projekt", "locher", "xapa", "techos", "relleno",
                 "glas", "gelb", "bild", "stahl", "blech"}
    added = {k: v for k, v in added.items()
             if any(c in k for c in " .,_@-") or (len(k) >= 6 and k not in bare_drop and not is_common(k))}
    changed = [k for k in before if B.keys.get(k, before[k]) != before[k]]
    if changed:
        raise SystemExit(f"refusing to change {len(changed)} existing keys, e.g. {changed[:5]}")
    keys.update(added)
    m["keys"] = keys
    json.dump(m, open(mp, "w", encoding="utf-8"), indent=0, sort_keys=True)
    print(f"added {len(added)} keys; mapping now {len(keys)}", flush=True)


if __name__ == "__main__":
    main()
