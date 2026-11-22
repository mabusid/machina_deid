"""Frozen mapping + Aho-Corasick replacer. Every replacement is byte-length preserving."""
import bisect
import json
import re

import ahocorasick

from .config import BIN_LONG_RUN, BIN_MIN_RUN, BIN_TEXTY_FRAC
from .pseudo import apply_case

_DIGIT = frozenset(range(48, 58))
_UPPER = frozenset(range(65, 91))
_LOWER = frozenset(range(97, 123))
_ASCII_ALNUM = _DIGIT | _UPPER | _LOWER

ASCII_RUN = re.compile(rb"[\x20-\x7e]{%d,}" % BIN_MIN_RUN)
U16_RUN = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")
_TEXTY = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 _.-:/\\@,()'")
BASE64_SPAN = re.compile(rb"base64,[A-Za-z0-9+/=\s]{16,}")


def _alnum(b: int) -> bool:
    return b in _ASCII_ALNUM or b >= 128


def _transition_ok(a: int, b: int) -> bool:
    """True if a word boundary exists between adjacent alnum bytes a|b."""
    if a >= 128 or b >= 128:
        return False
    if (a in _DIGIT) != (b in _DIGIT):
        return True
    return a in _LOWER and b in _UPPER  # camelCase


def _in_step_string(d: bytes, s: int, e: int) -> bool:
    ls = d.rfind(b"\n", 0, s) + 1
    if d.count(b"'", ls, s) % 2 == 0:
        return False
    j = e
    while j < len(d) and d[j] in b" \t":
        j += 1
    return not (j < len(d) and d[j] == 0x28)  # '(' follows an entity keyword


class Replacer:
    def __init__(self, keys: dict[str, str]):
        self.keys = keys
        self.A = ahocorasick.Automaton()
        for k, v in keys.items():
            assert len(k) == len(v) and k.isascii() and v.isascii(), k
            self.A.add_word(k, (len(k), v))
        self.empty = not keys
        if keys:
            self.A.make_automaton()

    @classmethod
    def load(cls, mapping_path):
        m = json.loads(open(mapping_path, encoding="utf-8").read())
        r = cls(m["keys"])
        r.owners = m.get("owners", {})
        oa, op = m.get("ole_all", {}), m.get("ole_prop", {})
        r.ole_all = cls({**m["keys"], **oa}) if oa else r
        r.ole_prop = cls({**m["keys"], **oa, **op}) if op else r.ole_all
        return r

    def _boundary(self, d: bytes, s: int, e: int) -> bool:
        if s > 0 and _alnum(d[s - 1]) and not _transition_ok(d[s - 1], d[s]):
            return False
        if e < len(d) and _alnum(d[e]) and not _transition_ok(d[e - 1], d[e]):
            return False
        return True

    def hits(self, data: bytes, protect=(), min_len: int = 0):
        """Non-overlapping (start, end, pseudo) hits, longest first."""
        if self.empty:
            return []
        low = data.lower().decode("latin-1")
        cands = []
        for end, (klen, pseudo) in self.A.iter(low):
            s, e = end - klen + 1, end + 1
            if klen >= min_len and self._boundary(data, s, e):
                cands.append((s, e, pseudo))
        if not cands:
            return []
        cands.sort(key=lambda t: (t[0] - t[1], t[0]))
        starts, ends, out = [], [], []
        for s, e, p in cands:
            i = bisect.bisect_left(starts, s)
            if i > 0 and ends[i - 1] > s:
                continue
            if i < len(starts) and starts[i] < e:
                continue
            if any(ps <= s < pe for ps, pe in protect):
                continue
            starts.insert(i, s)
            ends.insert(i, e)
            out.append((s, e, p))
        return out

    def replace_bytes(self, data: bytes, protect=(), min_len: int = 0) -> bytes:
        hs = self.hits(data, protect, min_len)
        if not hs:
            return data
        buf = bytearray(data)
        for s, e, p in hs:
            buf[s:e] = apply_case(data[s:e], p)
        return bytes(buf)

    def replace_str(self, s: str) -> str:
        b = s.encode("utf-8", "surrogateescape")
        nb = self.replace_bytes(b)
        return s if nb is b else nb.decode("utf-8", "surrogateescape")

    def replace_text(self, data: bytes, step: bool | None = None) -> bytes:
        """Whole-file text replacement; base64 payloads (embedded images) are left alone.

        STEP (ISO 10303-21): names only live inside '...' strings; entity keywords and enums
        outside them are format data, so only in-string hits are applied.
        """
        if step is None:
            step = data.lstrip()[:13] == b"ISO-10303-21;"
        protect = [m.span() for m in BASE64_SPAN.finditer(data)] if b"base64," in data else ()
        if not step:
            return self.replace_bytes(data, protect)
        hs = [h for h in self.hits(data, protect) if _in_step_string(data, h[0], h[1])]
        if not hs:
            return data
        buf = bytearray(data)
        for s, e, p in hs:
            buf[s:e] = apply_case(data[s:e], p)
        return bytes(buf)

    def replace_binary(self, data: bytes) -> bytes:
        """Edit only texty printable runs (ASCII and UTF-16LE) inside binary data.

        Compressed payloads are random bytes; a short key can match there by chance. ASCII runs
        must be long, or short but NUL-terminated (C / property-set strings), and never use
        3-letter keys. UTF-16LE runs cannot arise by chance (alternating NULs).
        """
        if self.empty:
            return data
        buf = None
        for m in ASCII_RUN.finditer(data):
            seg = m.group()
            if len(seg) < BIN_LONG_RUN and data[m.end():m.end() + 1] not in (b"\x00", b""):
                continue
            if sum(c in _TEXTY for c in seg) < BIN_TEXTY_FRAC * len(seg):
                continue
            new = self.replace_bytes(seg, min_len=4)
            if new is not seg:
                buf = buf or bytearray(data)
                buf[m.start():m.end()] = new
        for m in U16_RUN.finditer(data):
            seg = m.group()[::2]
            new = self.replace_bytes(seg)
            if new is not seg:
                buf = buf or bytearray(data)
                buf[m.start():m.end():2] = new
        return data if buf is None else bytes(buf)

    def count(self, data: bytes, binary: bool = False) -> dict:
        """Leak scan helper: which original keys still appear."""
        found = {}
        segs = [data] if not binary else [m.group() for m in ASCII_RUN.finditer(data)] + \
            [m.group()[::2] for m in U16_RUN.finditer(data)]
        for seg in segs:
            for s, e, _ in self.hits(seg):
                k = seg[s:e].lower().decode("latin-1")
                found[k] = found.get(k, 0) + 1
        return found
