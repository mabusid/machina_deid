"""Identity-candidate extractors used by harvest. All return iterables of (kind, value)."""
import io
import re
import zipfile

EMAIL = re.compile(rb"[A-Za-z0-9._%+\-]{2,64}@[A-Za-z0-9\-]{2,63}(?:\.[A-Za-z0-9\-]{2,63})+")
USERPATH = re.compile(rb"(?i)(?:[A-Z]:[\\/]+(?:Users|Documents and Settings)|/Users|/home)[\\/]+([A-Za-z0-9._\- ]{2,40}?)(?=[\\/])")
GH_URL = re.compile(rb"(?i)(?:github|gitlab)\.com/([A-Za-z0-9][A-Za-z0-9\-]{1,38})(?:/([A-Za-z0-9._\-]{1,100}))?")
URL_HOST = re.compile(rb"(?i)\bhttps?://([A-Za-z0-9\-.]{4,253})")
COPYRIGHT = re.compile(rb"(?i)(?:copyright|\(c\)|\xc2\xa9)\s*(?:\(c\)\s*)?(?:\d{4}(?:\s*[-,]\s*\d{4})*\s*,?\s*)?(?:by\s+)?([A-Z][A-Za-z0-9&.,' \-]{2,60})")
LABEL = re.compile(rb"(?i)\b(drawn|checked|approved|designed|designer|engineer|author|created|modified|reviewed)(?:\s+by)?\s*[:=]\s*([A-Z][A-Za-z.\-']+(?:[ \t]+[A-Z][A-Za-z.\-']+){0,2})")
XMP_CREATOR = re.compile(rb"<dc:(creator|rights|publisher|contributor)>.*?<rdf:li[^>]*>([^<]{2,80})</rdf:li>", re.S)
SVG_AGENT = re.compile(rb"<dc:(creator|rightsHolder|publisher)>\s*<cc:Agent>\s*<dc:title>([^<]{2,80})</dc:title>", re.S)
U16 = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")

STEP_FILE_NAME = re.compile(rb"FILE_NAME\s*\((.*?)\)\s*;", re.S)
STEP_STR = re.compile(rb"'((?:[^']|'')*)'")
DXF_LASTSAVED = re.compile(rb"\$LASTSAVEDBY\s*\r?\n\s*1\s*\r?\n([^\r\n]{1,80})")
FCSTD_PROP = re.compile(rb'<Property name="(CreatedBy|LastModifiedBy|Company)"[^>]*>\s*<String value="([^"]{1,120})"', re.S)
TMF_META = re.compile(rb'<metadata name="(Designer|Copyright|Author|LicenseTerms|Application)"[^>]*>([^<]{1,200})</metadata>', re.S)


def _s(b: bytes) -> str:
    return b.decode("utf-8", "ignore").strip()


EMAIL_DOMAIN = re.compile(rb"@[A-Za-z0-9\-]{2,63}(?:\.[A-Za-z0-9\-]{2,63})*\.[A-Za-z]{2,24}\b")
_LOCAL_CHARS = frozenset(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-")
LABEL_WORDS = (b"drawn", b"checked", b"approved", b"designed", b"designer", b"engineer",
               b"author", b"created", b"modified", b"reviewed")


def regex_entities(blob: bytes):
    """Each regex is gated by a cheap substring test; plain regex scans are too slow on STEP."""
    low = blob.lower()
    if b"@" in blob:
        for m in EMAIL_DOMAIN.finditer(blob):
            i = m.start()
            j = i
            while j > 0 and i - j < 64 and blob[j - 1] in _LOCAL_CHARS:
                j -= 1
            if i - j >= 2 and re.search(rb"[A-Za-z]", m.group()):
                yield "email", _s(blob[j:m.end()])
    if b"users" in low or b"/home/" in low or b"documents and settings" in low:
        for m in USERPATH.finditer(blob):
            yield "username", _s(m.group(1))
    if b"github.com/" in low or b"gitlab.com/" in low:
        for m in GH_URL.finditer(blob):
            yield "owner", _s(m.group(1))
            if m.group(2):
                yield "repo", _s(m.group(2)).removesuffix(".git")
    if b"http" in low:
        for m in URL_HOST.finditer(blob):
            yield "host", _s(m.group(1)).lower()
    if b"copyright" in low or b"(c)" in low or b"\xc2\xa9" in blob:
        for m in COPYRIGHT.finditer(blob):
            yield "copyright", _s(m.group(1))
    if any(w in low for w in LABEL_WORDS):
        for m in LABEL.finditer(blob):
            yield "label_person", _s(m.group(2))
    if b"<dc:" in blob:
        for m in XMP_CREATOR.finditer(blob):
            yield "xmp_" + _s(m.group(1)), _s(m.group(2))
        for m in SVG_AGENT.finditer(blob):
            yield "svg_" + _s(m.group(1)), _s(m.group(2))


def utf16_strings(blob: bytes) -> bytes:
    return b"\n".join(m.group()[::2] for m in U16.finditer(blob))


def binary_strings(blob: bytes) -> bytes:
    """Only the texty runs the transform would also touch: random bytes yield junk 'emails'."""
    from .matcher import ASCII_RUN, _TEXTY
    from .config import BIN_LONG_RUN, BIN_TEXTY_FRAC
    runs = [m.group() for m in ASCII_RUN.finditer(blob)
            if len(m.group()) >= BIN_LONG_RUN or blob[m.end():m.end() + 1] in (b"\x00", b"")]
    runs = [r for r in runs if sum(c in _TEXTY for c in r) >= BIN_TEXTY_FRAC * len(r)]
    return b"\n".join(runs) + b"\n" + utf16_strings(blob)


def step_header(blob: bytes):
    m = STEP_FILE_NAME.search(blob[:200000])
    if not m:
        return
    args = _split_top(m.group(1))
    # name, time_stamp, (authors), (organizations), preprocessor, originating_system, authorization
    if len(args) < 7:
        return
    yield "step_filename", _s(b"".join(STEP_STR.findall(args[0])))
    for field, kind in ((args[2], "step_author"), (args[3], "step_org"), (args[6], "step_authorization")):
        for s in STEP_STR.findall(field):
            yield kind, _s(s.replace(b"''", b"'"))


def _split_top(b: bytes):
    out, depth, cur, in_str, i = [], 0, bytearray(), False, 0
    while i < len(b):
        c = b[i:i + 1]
        if in_str:
            cur += c
            if c == b"'":
                if b[i + 1:i + 2] == b"'":
                    cur += b"'"
                    i += 1
                else:
                    in_str = False
        elif c == b"'":
            in_str = True
            cur += c
        elif c == b"(":
            depth += 1
            cur += c
        elif c == b")":
            depth -= 1
            cur += c
        elif c == b"," and depth == 0:
            out.append(bytes(cur))
            cur = bytearray()
        else:
            cur += c
        i += 1
    out.append(bytes(cur))
    return out


def iges_global(blob: bytes):
    lines = blob[:400000].split(b"\n")
    g = b"".join(ln[:72] for ln in lines if len(ln) >= 73 and ln[72:73] == b"G")
    if not g:
        return
    params, i, pdelim = [], 0, b","
    if g[:2] == b"1H":
        pdelim = g[2:3]
    while i < len(g) and len(params) < 30:
        m = re.match(rb"\s*(\d+)H", g[i:])
        if m:
            n = int(m.group(1))
            start = i + m.end()
            params.append(g[start:start + n])
            i = start + n
            j = g.find(pdelim, i)
            i = (j + 1) if j >= 0 else len(g)
        else:
            j = g.find(pdelim, i)
            params.append(g[i:j] if j >= 0 else g[i:])
            i = (j + 1) if j >= 0 else len(g)
    if len(params) >= 22:
        yield "iges_author", _s(params[20])
        yield "iges_org", _s(params[21])


def dxf_header(blob: bytes):
    for m in DXF_LASTSAVED.finditer(blob[:2000000]):
        yield "dxf_lastsavedby", _s(m.group(1))


def ole_props(data: bytes):
    import olefile
    ole = olefile.OleFileIO(data)
    md = ole.get_metadata()
    for attr, kind in (("author", "ole_author"), ("last_saved_by", "ole_lastsavedby"),
                       ("company", "ole_company"), ("manager", "ole_manager")):
        v = getattr(md, attr, None)
        if v:
            yield kind, _s(v if isinstance(v, bytes) else str(v).encode())
    for path in ole.listdir():
        if path[-1].startswith("\x05") and path[-1] not in ("\x05SummaryInformation", "\x05DocumentSummaryInformation"):
            try:
                props = ole.getproperties("/".join(path), convert_time=True)
            except Exception:
                continue
            for pid, v in props.items():
                if isinstance(v, (str, bytes)) and v:
                    yield "ole_other", _s(v if isinstance(v, bytes) else v.encode())


def pdf_meta(data: bytes):
    import pymupdf
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        md = doc.metadata or {}
        if md.get("author"):
            yield "pdf_author", md["author"]
        if md.get("creator"):
            yield "pdf_creator", md["creator"]
        xmp = doc.get_xml_metadata() or ""
        yield from regex_entities(xmp.encode())


def zip_members(data: bytes, max_member=8 << 20):
    """Yield (name, head_bytes) for zip members (for harvest only)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if info.is_dir() or info.flag_bits & 1:
                yield info.filename, b""
                continue
            with z.open(info) as f:
                yield info.filename, f.read(max_member)


def container_meta(blob: bytes):
    for m in FCSTD_PROP.finditer(blob):
        yield "fcstd_" + _s(m.group(1)).lower(), _s(m.group(2))
    for m in TMF_META.finditer(blob):
        yield "3mf_" + _s(m.group(1)).lower(), _s(m.group(2))
