"""Stage 2: candidates -> frozen length-preserving mapping (single-threaded, deterministic).

python -m deid.resolve
Reads  PRIVATE/harvest.json, optional PRIVATE/extra_entities.tsv (kind<TAB>value)
       and PRIVATE/exclude.txt (one value or key per line, case-insensitive).
Writes PRIVATE/mapping.json (keys + owners) and PRIVATE/review.tsv (for manual review).
"""
import argparse
import collections
import json
import os
import re
import secrets

from . import config as C
from .allowlist import ALLOW, PLACEHOLDER_VALUES, is_common
from .pseudo import Pseudonymizer, apply_case, is_word, tokens

PERSON = {"step_author", "ole_author", "ole_lastsavedby", "ole_manager", "pdf_author",
          "dxf_lastsavedby", "iges_author", "fcstd_createdby", "fcstd_lastmodifiedby",
          "3mf_designer", "3mf_author", "xmp_creator", "svg_creator", "label_person",
          "step_authorization", "person"}
ORG = {"step_org", "iges_org", "ole_company", "fcstd_company", "copyright", "3mf_copyright",
       "xmp_rights", "xmp_publisher", "svg_rightsholder", "svg_publisher", "org_slug", "org"}
DISTINCT_ONLY = {"repo", "project", "web_host"}
ORDER = ["email", "person", "username", "owner", "org", "distinct"]
GH_RESERVED = {"features", "orgs", "settings", "login", "about", "pricing", "topics", "sponsors",
               "marketplace", "apps", "assets", "user-attachments", "collections", "site", "blog",
               "enterprise", "security", "explore", "notifications", "issues", "pulls", "search"}
PUBLIC_MAIL = {"gmail", "googlemail", "yahoo", "hotmail", "outlook", "live", "msn", "icloud",
               "me", "aol", "protonmail", "gmx", "qq", "163", "126", "mail", "web", "yandex",
               "noreply", "users", "github"}
TLD_LIKE = ALLOW | {"www", "co", "ac", "com", "org", "net", "edu", "gov", "mil", "int", "info", "biz"}
FILE_TLDS = {"md", "py", "js", "ts", "sh", "rs", "go", "rb", "txt", "json", "xml", "yml",
              "yaml", "html", "css", "svg", "stl", "step", "stp", "zip", "exe", "dll", "bin",
              "dat", "log", "ini", "cfg", "csv", "pdf", "png", "jpg", "gif", "cpp", "hpp", "h",
              "c", "java", "lua", "ino", "sldprt", "sldasm", "ipt", "iam", "local", "lan"}
TLDS = set("""
com org net edu gov mil int info biz io co ai app dev me tv cc us uk ca au de fr it es nl be ch
at se no dk fi pl cz sk hu ro bg gr pt ie lu is ee lv lt si hr rs ba mk al ua by ru kz tr il
ae sa qa kw om bh ir pk in bd lk np cn hk tw jp kr sg my th vn ph id nz za ng ke eg ma tn dz
br ar cl pe uy py bo ec ve mx gt cr pa do pr cu jm tt eu asia tech online site xyz store
cloud design studio works systems solutions engineering company email space global group
""".split())
COPY_TAIL = re.compile(r"(?i)[.,;]?\s*(all rights reserved|licen[sc]ed|some rights|under\b|this\b).*$")


def distinctive(tok: str, strong=False) -> bool:
    t = tok.lower()
    if not t.isalpha() or t in ALLOW:
        return False
    if len(t) >= 4:
        return not is_common(t)
    return strong and len(t) == 3 and not is_common(t)


def clean(kind: str, v: str):
    v = v.strip().strip("'\"").strip()
    if kind == "copyright":
        v = COPY_TAIL.sub("", v).strip(" .,;-")
    if not v or len(v) > 80 or not re.search(r"[A-Za-z]{2}", v):
        return None
    if v.lower() in PLACEHOLDER_VALUES:
        return None
    words = [t for t in tokens(v) if is_word(t)]
    if not words or all(w.lower() in ALLOW for w in words):
        return None
    if not v.isascii():
        return None  # TODO: non-ASCII names need a byte-length-aware generator
    return v


def bucket(kind: str):
    if kind == "email":
        return "email"
    if kind in PERSON:
        return "person"
    if kind == "username":
        return "username"
    if kind == "owner":
        return "owner"
    if kind in ORG:
        return "org"
    if kind in DISTINCT_ONLY:
        return "distinct"
    return None  # review-only kinds (url_host, pdf_creator, ole_other, step_filename, ...)


class Builder:
    def __init__(self, P: Pseudonymizer, exclude: set):
        self.P = P
        self.keys: dict[str, str] = {}
        self.owners: dict[str, str] = {}
        self.exclude = exclude

    def add(self, key: str, pseudo: str) -> bool:
        k = key.lower()
        if len(k) < 3 or k in self.keys or k in self.exclude or k in ALLOW:
            return False
        if not re.search(r"[a-z]", k) or len(k) != len(pseudo):
            return False
        if k.isalpha() and is_common(k):  # a bare common word would rewrite format data everywhere
            return False
        self.keys[k] = pseudo
        return True

    def tok_keys(self, value: str, strong: bool, style="name"):
        """Sub-tokens become standalone keys only at 4+ letters; 3-letter keys need a whole value."""
        for t in tokens(value):
            if is_word(t) and len(t) >= 4 and distinctive(t, strong):
                self.add(t, self.P.token(t, style))

    def phrase_all(self, value: str, style_for=lambda i, t: "name") -> str:
        return self.P.phrase(value, lambda t: t.lower() not in ALLOW, style_for)

    def person(self, v: str):
        words = [t for t in tokens(v) if is_word(t)]
        if len(words) == 1:
            if distinctive(words[0], strong=True):
                self.add(v, self.phrase_all(v))
            return
        first, last = words[0].lower(), words[-1].lower()
        pf, pl = self.P.token(first, "first"), self.P.token(last, "last")
        ws = [w.lower() for w in words]
        if any(distinctive(w, True) for w in ws) or len(v) >= 8:
            self.add(v, self.P.phrase(v, lambda t: True, lambda i, t: "first" if t == first else "last" if t == last else "name"))
            for sep in (" ", ".", "_", "-", ""):
                self.add(first + sep + last, pf + sep + pl)
            self.add(f"{last}, {first}", f"{pl}, {pf}")
            self.add(f"{last} {first}", f"{pl} {pf}")
            for sep in (". ", ".", " ", "", "_"):
                self.add(first[0] + sep + last, pf[0] + sep + pl)
            self.add(last + first[0], pl + pf[0])
        self.tok_keys(v, strong=True, style="last")

    def email(self, v: str):
        local, _, domain = v.lower().partition("@")
        labels = domain.split(".")
        if labels[-1] in FILE_TLDS or len(local) < 2 or not re.search(r"[a-z]{2}", local):
            return
        if labels[-1] not in TLDS or any(len(lb) < 2 for lb in labels):
            return
        dom_orig = v.partition("@")[2]
        if any(not (lb.islower() or lb.isupper() or lb.istitle()) for lb in dom_orig.split(".") if lb.isalpha()):
            return  # mixed-case labels like 'Da3.PGc' come from encoded/binary noise
        public = any(lb in PUBLIC_MAIL for lb in labels[:-1])
        pl = self.P.phrase(local, lambda t: t not in ALLOW)
        pd = domain if public else ".".join(
            lb if lb in TLD_LIKE else self.P.phrase(lb, lambda t: True) for lb in labels)
        self.add(v, pl + "@" + pd)
        if not public:
            for lb in labels:
                if lb not in TLD_LIKE and len(lb) >= 3:
                    self.add(lb, self.P.phrase(lb, lambda t: True))
        if re.search(r"[a-z]{3}", local) and not all(t in ALLOW or not t.isalpha() for t in tokens(local)):
            parts = [t for t in tokens(local) if is_word(t)]
            if len(parts) == 1 and len(parts[0]) >= 4 and distinctive(parts[0], True):
                self.add(local, pl)
            elif len(parts) >= 2 and len(local) >= 5:
                self.add(local, pl)

    def username(self, v: str):
        if " " in v.strip():
            return self.person(v)
        p = self.phrase_all(v)
        if any(distinctive(t, True) for t in tokens(v) if is_word(t)):
            self.add(v, p)
        for pre in ("users\\", "users/", "home/", "users\\\\"):
            self.add(pre + v, pre + p)

    def owner(self, v: str):
        if v.lower() in GH_RESERVED:
            return
        p = self.phrase_all(v)
        self.owners[v] = apply_case(v.encode(), p).decode()
        words = [t for t in tokens(v) if is_word(t)]
        if any(distinctive(w, True) for w in words) or (len(words) >= 2 and len(v) >= 8):
            self.add(v, p)
            if len(words) >= 2:
                for sep in (" ", "-", "_", ""):
                    self.add(sep.join(w.lower() for w in words), sep.join(self.P.token(w) if w.lower() not in ALLOW else w.lower() for w in words))
        self.tok_keys(v, strong=True)

    def org(self, v: str):
        words = [t for t in tokens(v) if is_word(t)]
        if not any(distinctive(w) for w in words) and len(words) < 2:
            return
        p = self.phrase_all(v)
        if any(distinctive(w) for w in words) or len(v) >= 10:
            self.add(v, p)
        self.tok_keys(v, strong=False)

    def distinct(self, v: str):
        self.tok_keys(v, strong=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harvest", default=str(C.PRIVATE / "harvest.json"))
    ap.add_argument("--private", default=str(C.PRIVATE))
    a = ap.parse_args()
    priv = a.private
    os.makedirs(priv, exist_ok=True)

    sk = os.path.join(priv, "secret.key")
    if not os.path.exists(sk):
        with open(sk, "w") as f:
            f.write(secrets.token_hex(32))
    secret = bytes.fromhex(open(sk).read().strip())

    h = json.load(open(a.harvest, encoding="utf-8"))
    counts = collections.Counter()
    for kv, n in h["counts"].items():
        k, _, v = kv.partition("\t")
        counts[(k, v)] += n
    extra = os.path.join(priv, "extra_entities.tsv")
    if os.path.exists(extra):
        for line in open(extra, encoding="utf-8"):
            if "\t" in line and not line.startswith("#"):
                k, v = line.rstrip("\n").split("\t", 1)
                counts[(k, v)] += 10**6
    exclude = set()
    exf = os.path.join(priv, "exclude.txt")
    if os.path.exists(exf):
        exclude = {l.strip().lower() for l in open(exf, encoding="utf-8") if l.strip() and not l.startswith("#")}

    if any(k == "host" for k, _ in counts):  # host from a path segment is a source website
        for (k, v), n in list(counts.items()):
            if k == "host":
                ex = h["examples"].get(f"{k}\t{v}", "")
                counts[("web_host" if ex.startswith(("sources/web/", "sources/gitlab/")) and v.split(".")[0] not in ("gitlab", "github") else "url_host", v)] += n
                del counts[(k, v)]

    reserved = {t.lower() for (k, v) in counts for t in tokens(v) if is_word(t)}
    P = Pseudonymizer(secret, reserved=reserved)
    B = Builder(P, exclude)
    entries = []
    for (k, v), n in counts.items():
        b = bucket(k)
        cv = clean(k, v) if b else None
        if b and cv and cv.lower() not in exclude:
            entries.append((ORDER.index(b), -n, cv.lower(), b, k, cv, n, v))
        else:
            entries.append((99, -n, v.lower(), None, k, cv, n, v))
    entries.sort()

    review = []
    for _, _, _, b, k, cv, n, v in entries:
        before = len(B.keys)
        if b:
            getattr(B, b)(cv)
        review.append((k, v, n, b or "review-only", len(B.keys) - before, h["examples"].get(f"{k}\t{v}", "")))

    with open(os.path.join(priv, "mapping.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "keys": B.keys, "owners": B.owners}, f, indent=0, sort_keys=True)
    with open(os.path.join(priv, "review.tsv"), "w", encoding="utf-8") as f:
        f.write("kind\tvalue\tcount\tpolicy\tkeys_added\texample\n")
        for r in sorted(review, key=lambda r: (r[3] == "review-only", -r[2])):
            f.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
    print(f"resolve: {len(B.keys)} keys, {len(B.owners)} owners -> {priv}/mapping.json ; review {priv}/review.tsv")


if __name__ == "__main__":
    main()
