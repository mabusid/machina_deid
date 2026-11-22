"""Build Attempt-5 extended mapping from mapping.attempt3.json without changing any existing keys.

Existing `keys` and `owners` stay byte-identical so NO file paths change (zero broken links).
Adds:
  - `ole_prop` / `ole_all`: ALL Inventor (\x05Zrxrt..., \x05Qz4dg..., \x05Aaalp...) and SolidWorks
    (\x05SummaryInformation, ISolidWorksInformation) saved-account / author / company strings.
  - `pdf_text`: emails, URLs/domains, person names with real given names, and known recurring
    PDF organizations/institutions/copyright holders across all 10,249 PDFs.
  - `pdf_meta`: all harvested pdf_author values (incl. short/generic ones) for PDF metadata only.
  - `unicode_map`: non-ASCII person/account/company names -> consistent ASCII pseudonyms.
  - `text_drop`: 3 false-positive keys dropped from content replacement (paths unchanged).

python scripts/extend_attempt5.py --rels /root/private/attempt2-rels.txt
"""
import argparse
import collections
import json
import os
import re
import sys
from multiprocessing import Pool

import olefile
import pymupdf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deid import config as C  # noqa: E402
from deid.allowlist import ALLOW, PLACEHOLDER_VALUES, is_common  # noqa: E402
from deid.pseudo import Pseudonymizer, apply_case, is_word, tokens  # noqa: E402
from deid.resolve import FILE_TLDS, GENERIC_ACCOUNTS, PUBLIC_MAIL, TLD_LIKE, TLDS, Builder  # noqa: E402

EM = re.compile(r"\b[A-Za-z0-9._%+\-]{2,40}@[A-Za-z0-9.\-]{2,50}\.[A-Za-z]{2,12}\b")
URL = re.compile(r"(?i)\b(?:https?://)?(?:www\.)([A-Za-z0-9\-]{3,40}\.[A-Za-z]{2,12}(?:\.[A-Za-z]{2,6})?)\b")
NAME = re.compile(r"\b([A-Z][a-z]{2,}|[A-Z]\.)[ ]+([A-Z][a-z]{2,})\b")
LASTF = re.compile(r"\b([A-Z][a-z]{2,}),[ ]+([A-Z][a-z]{2,})\b")

PUBLIC_DOMAINS = {
    "github.com", "gitlab.com", "youtube.com", "google.com", "creativecommons.org",
    "w3.org", "doi.org", "wikipedia.org", "amazon.com", "amazon.it", "aliexpress.com",
    "asme.org", "iso.org", "nist.gov", "springerlink.com", "elsevier.com", "cairographics.org",
    "microsoft.com", "adobe.com", "autodesk.com", "solidworks.com", "freecad.org",
    "thingiverse.com", "grabcad.com", "printables.com", "reprap.org", "cern.ch",
}

GIVEN = set("""
ada adam adrian adriana agustin alan albert alejandro alex alexander alexandra alice alicia
alison allan allen allison alyssa amanda amber amelia amy andrea andres andrew angela
angelica anita ann anna anne anthony antonio april arthur ashley austin barbara barry
beatriz ben benjamin bernat bernard bernhard beverly bill billy blake bob bobby bonnie
bradley brandon brenda brent brett brian bruce bryan caleb calvin cameron carl carla
carlos carmen carol caroline carolyn carrie catherine cathy cecilia chad charles charlotte
cheryl chris christian christina christine christopher cindy claire clara clarence claude
claudia cody colin connie craig cristina crystal cynthia dale dana daniel danielle danny
darren dave david dawn dean debbie deborah denis dennis derek diana diane diego dominic
donald donna doris douglas duane dylan earl eddie edgar edith eduardo edward edwin eileen
elaine elena elijah elizabeth ella ellen elmer emily emma eric erica erik erin ernest
esther ethan eugene eva evan evelyn faith felix fernando flora florence floyd francis
frank franklin fred frederick gabriel gail gary gene geoffrey george gerald gerhard
gina giovanni gladys glenn gloria gordon grace grant greg gregory gretchen guillermo
gwen haley hannah harold harry harvey heather hector heidi helen henri henry herbert
holly horst howard hugh hugo ian ida ines irene irma isaac isabel ivan jack jacob
jacqueline jacques jaime jake james jamie jan janet janice jared jason javier jay
jean jeff jeffrey jenna jennifer jenny jeremy jerry jesse jessica jess jessie jesus
jill jim jimmy joan joann joanna joanne jodi jody joe joel john johnny jon jonathan
jordan jorge jose joseph josh joshua joy joyce juan judith judy julia julian julien
julio june justin kara karen karl katherine kathleen kathryn kathy katie kay keith
kelly ken kenneth kerry kevin kim kimberly kirk kristen kristin kristina kyle lance
larry laura lauren laurie lawrence lee leo leon leonard leslie lewis lillian lily
linda lindsay lindsey lisa logan lois lori lorraine louis louise lucas lucia lucy
luis luke lydia lynn mabel madeleine madison manuel marc marcel marco marcos marcus
margaret maria marian marianne marie marilyn marina mario marion marjorie mark marlene
marsha marshall martha martin marvin mary mathew matteo matthew maurice max megan
melanie melissa melody michael michele michelle miguel mike mildred milton miriam
mitchell monica morgan morris nancy natalie natasha nathan nathaniel neil nelson
nicholas nicolas nicole nina noah noel nora norma norman olga olive oliver olivia
oscar oswald owen pablo pam pamela patricia patrick patsy patty paul paula pauline
pedro peggy penny perry peter philip philippe phillip phyllis pierre preston rachel
ralph ramon randall randy raul ray raymond rebecca regina rene renee ricardo richard
rick ricky rita robert roberto robin rodney roger roland roman ron ronald ronda rosa
rose rosemary ross roy ruben russell ruth ryan sabrina sally sam samantha samuel sandra
sara sarah scott sean sebastian sergio seth shannon shari sharon shawn sheila shelley
sherri sherry shirley sidney silvia sofia sonia sonya stacy stacey stanley stefan
stefanie stella stephanie stephan stephen steve steven stuart sue susan suzanne sylvia
tamara tammy tanya tara taylor ted teresa teri terrance terrence terry theodore theresa
thomas tiffany tim timothy tina todd tom tommy toni tony tracey tracy travis tricia
troy tyler valerie vanessa veronica vicki vickie victor victoria vincent viola violet
virginia vivian wade walter wanda warren wayne wendy wesley willard william willie
wilma yvonne zachary zoe hans klaus wolfgang juergen jurgen dieter helmut werner
manfred heinz franz josef otto ernst friedrich wilhelm heinrich ludwig andreas markus
matthias torsten uwe ralf rainer bernd holger olaf sven nils ole kai florian tobias
dirk jens alain christophe laurent thierry pascal yves antoine francois guillaume
michel fabian alejandro myriam callum magnus diego carrasco velazquez
""".split())

# Recurring PDF organizations, institutions, brands, and people verified in corpus PDFs
CURATED_ORGS = [
    "Fundacio CIM", "Aleph Objects, Inc.", "Aleph Objects",
    "California Institute of Technology", "Massachusetts Institute of Technology",
    "Caltech", "University of Michigan", "Neurobionics Lab",
    "Precious Plastic", "One Army", "Dave Hakkens", "RT Corporation",
    "E3D-Online Ltd", "E3D-Online", "Miller Electric Mfg", "Miller Electric",
    "Tertiary Infotech Academy", "Cairn Research", "Optotune Switzerland", "Optotune",
    "Advanced Dimensional Management", "Woking Precision Models",
    "Shenzhen ZhongLing Technology", "Zhejiang Tongzhu Technology",
    "Facultad Regional Chubut", "Ostschweizer Fachhochschule",
    "ETH Zurich", "TU Wien", "NYU Tandon", "Universiteit Brussel",
    "Keychron", "OpenLoong", "QingLoong", "Roboparty", "Sienci Labs",
    "CamInstructor", "Littelfuse", "Schaffner", "Mertz", "LulzBot",
    "Marcos Cerezo", "Marcos Briones", "Bernat Poll", "Jon Castillo",
    "Diego Victor Saavedra Ravier", "Saavedra Ravier", "Maurice Miro",
    "Schmid Patrick", "Thomas Guillod", "Myriam Ayass", "Callum Hollick",
    "Magnus Bolt", "Bryan Fischer", "Joshua Vasquez", "F. Azocar",
    "S. Aston", "M. Mooney", "Mooney, Alejandro", "A. Vecchio",
    "L. Spruyt", "L. Amann", "M. Timmers", "T. Westbury",
    "Fabian Hochecker", "U. Rapp", "J. Odell", "M. Meyer", "C. Torrie",
    "C. Robertson", "E. Sanchez", "E.SANCHEZ", "C. Echols", "P. Fritschel", "D. Coyne",
    "B. Moore", "J. Sperling", "L. Renaglia",
    "Howard Hughes Medical Institute", "Hughes Medical Institute", "HHMI", "Janelia",
    "Senthur Raj Ayyappan", "Senthur Raj", "Ayyappan", "Thorlabs",
    "Windward Spindle Technology", "G1MRA", "Telerobot", "Becchi",
    "Conrad Electronic", "Open Source Ecology", "Istituto Italiano di Tecnologia",
    "UNAM-FES-CUAUTITLAN", "flickingerd",
]

CURATED_UNICODE = [
    "Fundació CIM", "Jesús Carrasco", "Andrés Velázquez", "Víctor Saavedra Ravier",
    "Jesús", "Andrés", "Velázquez", "Víctor", "Séba", "séba", "SÉBA",
    "Marianne Röchling", "Malte Schöps", "Raphaël Bahisson", "Raphael Brandão",
    "Josef Průša", "Fam. Martínez Paéz", "The Mâââvin", "Rémi",
    "UNAM-FES-CUAUTITLÁN",
    "Сергей", "东莞市万绵电子有限公司", "萝博派对", "苏朗", "冠禎 林",
    "黄海生", "迈迪01", "王术江", "山本英貴", "高越阳", "王静", "王 磊",
    "微软用户", "前春 周", "水谷 武司",
]

OLE_SKIP_STRINGS = {
    "property set name", "inventor summary information", "inventor document summary information",
    "design tracking properties", "design tracking control", "inventor user defined properties",
    "modeling", "generic", "default", "unknown", "none", "null", "n/a", "solid edge",
    "solidworks", "autodesk", "inventor", "microsoft", "windows", "iso metric part.par",
    "iso metric assembly.asm", "managed by terraform", "component type", "sw-author",
    "assembly type", "part", "assembly", "drawing", "sheet metal", "weldment",
    "stainless steel", "aluminum 6061", "steel", "carbon steel", "mild steel", "brass",
    "copper", "plastic", "abs", "pla", "nylon", "titanium", "rubber", "generic",
    "a", "b", "c", "d", "e", "f", "1", "2", "3", "4", "5",
}

INV_PROP_STREAMS = (
    "\x05Zrxrt4arFafyu34gYa3l3ohgHg",  # Inventor Summary Info (Author, SavedBy)
    "\x05Qz4dgm1gRjudbpksAayal4qdGf",  # Inventor Design Tracking Control (SavedBy)
    "\x05Aaalpg0m0wzvuhc41dwauxbwJc",  # Inventor Doc Summary (Company, Manager)
)


def parse_propset_vals(raw):
    out = []
    for m in re.finditer(rb"[\x1e\x1f]\x00\x00\x00", raw):
        o, wide = m.end(), raw[m.start()] == 0x1F
        if o + 4 > len(raw):
            continue
        n = int.from_bytes(raw[o:o + 4], "little") * (2 if wide else 1)
        if not 1 <= n <= 256 or o + 4 + n > len(raw):
            continue
        s = raw[o + 4:o + 4 + n]
        try:
            v = s.decode("utf-16-le" if wide else "utf-8").split("\x00", 1)[0].strip()
        except Exception:
            try:
                v = s.decode("latin-1").split("\x00", 1)[0].strip()
            except Exception:
                continue
        if v:
            out.append(v)
    return out


def ok_ole_account(v):
    if not v or len(v) < 2 or len(v) > 64:
        return False
    low = v.lower()
    if low in OLE_SKIP_STRINGS:
        return False
    if v.isdigit() or re.fullmatch(r"[\d.\-:/ ]+", v):
        return False
    if re.search(r"(?i)(solidworks|autodesk|inventor|solid edge|microsoft|build \d|:\\|\.adsklib|\.par$|\.asm$|\.ipt$|\.sld)", v):
        return False
    if not re.search(r"[A-Za-z\u00c0-\u024f\u0400-\u04ff\u4e00-\u9fff]", v):
        return False
    return True


def _work_ole(rel):
    p = os.path.join(C.INPUT, rel)
    if not os.path.exists(p):
        return set()
    found = set()
    try:
        o = olefile.OleFileIO(p)
    except Exception:
        return found
    try:
        md = o.get_metadata()
        for f in (md.author, md.last_saved_by, md.company):
            if not f:
                continue
            if isinstance(f, bytes):
                try:
                    s = f.decode("utf-8")
                except UnicodeDecodeError:
                    s = f.decode("latin-1")
            else:
                s = f
            s = s.split("\x00", 1)[0].strip()
            if ok_ole_account(s):
                found.add(s)
    except Exception:
        pass
    for st in INV_PROP_STREAMS:
        if o.exists(st):
            try:
                for v in parse_propset_vals(o.openstream(st).read()):
                    if ok_ole_account(v):
                        found.add(v)
            except Exception:
                pass
    return found


def _work_pdf(rel):
    p = os.path.join(C.INPUT, rel)
    if not os.path.exists(p):
        return set(), set(), set()
    emails, urls, names = set(), set(), set()
    try:
        doc = pymupdf.open(p)
        if doc.needs_pass:
            return emails, urls, names
        for i in range(min(len(doc), 5)):
            t = doc[i].get_text()
            for m in EM.findall(t):
                emails.add(m.lower())
            for m in URL.findall(t):
                d = m.lower()
                if d not in PUBLIC_DOMAINS and not any(d.endswith("." + pd) for pd in PUBLIC_DOMAINS):
                    urls.add(d)
            for a, b in NAME.findall(t):
                al, bl = a.rstrip(".").lower(), b.lower()
                if a.endswith("."):
                    if len(bl) >= 4 and not is_common(bl) and bl not in ALLOW:
                        names.add(f"{a[0]}. {b}")
                elif (al in GIVEN or bl in GIVEN) and len(bl) >= 4 and not is_common(bl) and bl not in ALLOW:
                    names.add(f"{a} {b}")
            for a, b in LASTF.findall(t):
                al, bl = a.lower(), b.lower()
                if bl in GIVEN and len(al) >= 4 and not is_common(al) and al not in ALLOW:
                    names.add(f"{b} {a}")
    except Exception:
        pass
    return emails, urls, names


def seed(P, *dicts):
    for d in dicts:
        for k, v in d.items():
            kt, vt = tokens(k), tokens(v)
            if len(kt) != len(vt):
                continue
            for tk, tv in zip(kt, vt):
                if is_word(tk) and is_word(tv) and tk not in P.map:
                    P.map[tk] = tv
                    P.used.add(tv)


def ascii_pseudo_for_unicode(P, s: str) -> str:
    """Deterministic ASCII pseudonym for a non-ASCII string, matching char length (or UTF-8 len >= 4)."""
    # Keep words separated; map each token deterministically via P.token
    parts = re.split(r"(\s+)", s.strip())
    out = []
    for p in parts:
        if not p or p.isspace():
            out.append(p)
            continue
        if p.isascii() and p.isalpha():
            pl = P.token(p.lower(), "name")
            out.append(apply_case(p.encode("ascii"), pl).decode("ascii"))
        else:
            # Generate deterministic ASCII token of same char length (min 4 for short CJK names)
            n = max(len(p), 4) if any(ord(c) > 0x2E80 for c in p) else max(len(p), 3)
            key = f"u_{p.lower()}"
            if key in P.map:
                tok = P.map[key]
            else:
                for attempt in range(200):
                    cand = P._gen(key, n, "last" if n >= 5 else "name", attempt)
                    if cand not in P.used and cand not in P.reserved:
                        tok = cand
                        break
                else:
                    tok = P._gen(key, n, "name", 0)
                P.map[key] = tok
                P.used.add(tok)
            out.append(tok.upper() if p.isupper() else tok.capitalize())
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rels", required=True)
    a = ap.parse_args()
    all_rels = [l.rstrip("\n") for l in open(a.rels, encoding="utf-8") if l.strip()]
    pdf_rels = [r for r in all_rels if r.lower().endswith(".pdf")]
    ole_rels = [r for r in all_rels if not r.lower().endswith(".pdf")]
    print(f"Scanning {len(ole_rels)} OLEs and {len(pdf_rels)} PDFs...", flush=True)

    ole_cnt = collections.Counter()
    with Pool(os.cpu_count() or 2) as pool:
        for s in pool.imap_unordered(_work_ole, ole_rels, chunksize=32):
            ole_cnt.update(s)
    print(f"OLE accounts harvested: {len(ole_cnt)} unique, top15: {ole_cnt.most_common(15)}", flush=True)

    ec, uc, nc = collections.Counter(), collections.Counter(), collections.Counter()
    with Pool(os.cpu_count() or 2) as pool:
        for emails, urls, names in pool.imap_unordered(_work_pdf, pdf_rels, chunksize=16):
            ec.update(emails)
            uc.update(urls)
            nc.update(names)
    print(f"PDF harvested: emails={len(ec)} urls={len(uc)} names={len(nc)}", flush=True)

    mp = C.PRIVATE / "mapping.json"
    base_mp = C.PRIVATE / "mapping.attempt3.json"
    if not base_mp.exists():
        base_mp = mp
    m = json.load(open(base_mp, encoding="utf-8"))
    keys = dict(m["keys"])
    ole_all = dict(m.get("ole_all", {}))
    ole_prop = dict(m.get("ole_prop", {}))
    exclude = set()
    for fn in ("exclude.txt", "pdf_names_drop.txt"):
        p = C.PRIVATE / fn
        if p.exists():
            exclude |= {l.strip().lower() for l in open(p, encoding="utf-8") if l.strip() and not l.startswith("#")}

    secret = bytes.fromhex(open(C.PRIVATE / "secret.key").read().strip())
    reserved = {t.lower() for s in list(keys) + list(ole_all) + list(ole_prop) + list(ec) + list(nc) + list(ole_cnt)
                for t in tokens(s) if is_word(t)}
    P = Pseudonymizer(secret, reserved=reserved)
    seed(P, keys, ole_all, ole_prop)

    # 1. Expand OLE accounts (ASCII -> ole_prop / ole_all; non-ASCII -> unicode_map)
    unicode_map = {}
    for u in CURATED_UNICODE:
        unicode_map[u.lower()] = ascii_pseudo_for_unicode(P, u)

    added_ole_prop = 0
    for val, _cnt in ole_cnt.most_common():
        if not val.isascii():
            if val.lower() not in unicode_map:
                unicode_map[val.lower()] = ascii_pseudo_for_unicode(P, val)
            continue
        low = val.lower()
        if low in keys or low in ole_prop or low in ole_all or len(low) < 2:
            continue
        p = P.phrase(low, lambda t: True)
        if len(p) != len(low) or p == low:
            continue
        ole_prop[low] = p
        added_ole_prop += 1
        if len(low) >= 4 and low not in GENERIC_ACCOUNTS and low not in ALLOW and not is_common(low) and low not in exclude:
            ole_all[low] = p
    print(f"OLE added: +{added_ole_prop} ole_prop (now {len(ole_prop)}), ole_all now {len(ole_all)}", flush=True)

    # 2. Build pdf_text (ONLY for PDF page text/metadata; does NOT touch `keys`, so ZERO path renames!)
    B = Builder(P, exclude)
    B.keys = dict(keys)
    # Emails
    for email, _n in ec.most_common():
        local, _, domain = email.partition("@")
        labels = domain.split(".")
        if len(labels) < 2 or labels[-1] in FILE_TLDS or labels[-1] not in TLDS:
            continue
        if len(local) < 2 or not re.search(r"[a-z]{2}", local):
            continue
        public = any(lb in PUBLIC_MAIL for lb in labels[:-1])
        pl = P.phrase(local, lambda t: t not in ALLOW)
        pd = domain if public else ".".join(
            lb if lb in TLD_LIKE else P.phrase(lb, lambda t: True) for lb in labels)
        B.add(email, pl + "@" + pd)
        if not public:
            B.add(domain, pd)
            for lb in labels:
                if lb not in TLD_LIKE and len(lb) >= 5 and not is_common(lb):
                    B.add(lb, P.phrase(lb, lambda t: True))
    # URLs / domains
    for dom, cnt in uc.most_common():
        labels = dom.split(".")
        if len(labels) < 2 or labels[-1] not in TLDS or labels[-1] in FILE_TLDS:
            continue
        pd = ".".join(lb if lb in TLD_LIKE else P.phrase(lb, lambda t: True) for lb in labels)
        if len(pd) == len(dom) and pd != dom:
            B.add(dom, pd)
            B.add("www." + dom, "www." + pd)
    # Curated PDF orgs / people (whole phrases + distinctive surnames/brands)
    for phrase in CURATED_ORGS:
        low = phrase.lower()
        p = P.phrase(low, lambda t: is_word(t) and t not in ALLOW)
        if len(p) == len(low) and p != low:
            B.keys.setdefault(low, p)
        words = [w for w in tokens(low) if is_word(w)]
        if len(words) == 2 and (words[0] in GIVEN or len(words[0]) == 1):
            B.person(phrase)
    # Auto-harvested given-name person pairs from PDFs (phrases + initials only; no noisy bare words!)
    for name, cnt in nc.most_common():
        if cnt < 2:
            continue
        low = name.lower()
        words = [w for w in tokens(low) if is_word(w)]
        if len(words) != 2:
            continue
        a, b = words
        pa = P.token(a, "first") if len(a) > 1 else a
        pb = P.token(b, "last")
        for k, v in [
            (f"{a} {b}", f"{pa} {pb}"),
            (f"{a[0]}. {b}", f"{pa[0]}. {pb}"),
            (f"{a[0]}.{b}", f"{pa[0]}.{pb}"),
            (f"{b}, {a}", f"{pb}, {pa}"),
        ]:
            if k not in B.keys and k not in exclude and len(k) == len(v) and k != v:
                B.keys[k] = v
        # Also add distinctive surnames appearing in >= 5 PDFs (e.g. Cerezo, Briones, Poll, Castillo)
        if cnt >= 5 and len(b) >= 5 and not is_common(b) and b not in ALLOW and b not in exclude:
            B.keys.setdefault(b, pb)

    pdf_text = {k: v for k, v in B.keys.items() if k not in keys}

    # 3. Build pdf_meta: ALL harvested pdf_author values (for PDF /Author & dc:creator metadata only!)
    pdf_meta = {}
    h = json.load(open(C.PRIVATE / "harvest.json", encoding="utf-8"))
    for kv, _cnt in h["counts"].items():
        kind, val = kv.split("\t", 1)
        if kind != "pdf_author":
            continue
        v = val.strip()
        if not v or len(v) > 80:
            continue
        if not v.isascii():
            if v.lower() not in unicode_map:
                unicode_map[v.lower()] = ascii_pseudo_for_unicode(P, v)
            continue
        low = v.lower()
        if low in keys or low in pdf_text or low in pdf_meta or len(low) < 2:
            continue
        if low in ("nx", "nist", "first", "cover", "anonymous", "(anonymous)", "none", "unknown"):
            continue
        p = P.phrase(low, lambda t: True)
        if len(p) == len(low) and p != low:
            pdf_meta[low] = p

    # Verify ZERO existing keys changed
    assert m["keys"] == keys, "existing keys must not change"
    m["ole_all"] = ole_all
    m["ole_prop"] = ole_prop
    m["pdf_text"] = pdf_text
    m["pdf_meta"] = pdf_meta
    m["unicode_map"] = unicode_map
    m["text_drop"] = ["dataset", "organisation", "a com"]
    json.dump(m, open(mp, "w", encoding="utf-8"), indent=0, sort_keys=True)
    print(f"DONE: keys={len(keys)} (unchanged) pdf_text=+{len(pdf_text)} pdf_meta=+{len(pdf_meta)} "
          f"ole_prop={len(ole_prop)} ole_all={len(ole_all)} unicode_map={len(unicode_map)}", flush=True)


if __name__ == "__main__":
    main()
