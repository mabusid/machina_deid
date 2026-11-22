"""Bytes-in / bytes-out handlers. Each returns new bytes, or None when nothing changed.

Any exception means "not safe": the caller keeps the original bytes.
Handlers validate their own output before returning it.
"""
import gzip
import io
import re
import struct
import tarfile
import zipfile
import zlib

from . import config as C
from .paths import ext_of, rename_member

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
SQLITE_TEXT = re.compile(rb"[\x20-\x7e]{4,}")


class Unsafe(Exception):
    pass


def classify(name: str, head: bytes) -> str:
    ext = ext_of(name)
    if ext in C.COPY_EXTS:
        return "copy"
    if head.startswith(b"%PDF") or ext == ".pdf":
        return "pdf"
    if head[:2] == b"\x1f\x8b":
        return "tar" if name.lower().endswith(C.TAR_SUFFIXES) else "gzip"
    if name.lower().endswith(C.TAR_SUFFIXES) or (len(head) > 262 and head[257:262] == b"ustar"):
        return "tar"
    if head[:4] == b"PK\x03\x04" or head[:4] == b"PK\x05\x06":
        return "zip_archive" if ext in C.ZIP_ARCHIVE_EXTS else "zip_container"
    if ext == ".stl":
        return "stl"
    if ext in C.IMAGE_EXTS or head[:8] == b"\x89PNG\r\n\x1a\n" or head[:3] == b"\xff\xd8\xff":
        return "image"
    if head.startswith(OLE_MAGIC):
        return "ole"
    if head.startswith(b"SQLite format 3\x00"):
        return "sqlite"
    if ext in C.BINARY_STRINGS_EXTS:
        return "binary"
    if ext in C.TEXT_EXTS or _looks_text(head):
        return "text"
    return "binary"


def _looks_text(head: bytes) -> bool:
    sample = head[:65536]
    if not sample or b"\x00" in sample:
        return False
    bad = sum(1 for c in sample if c < 9 or 13 < c < 32)
    return bad < 0.01 * len(sample)


def process(data: bytes, name: str, R, depth: int = 0, log=None):
    """Returns (new_bytes_or_None, handler_name)."""
    kind = classify(name, data[:1024])
    fn = HANDLERS.get(kind)
    if fn is None or not data:
        return None, kind
    return fn(data, name, R, depth, log), kind


def _safe_member(data, name, R, depth, log):
    try:
        new, kind = process(data, name, R, depth + 1, log)
        return new
    except Exception as e:  # member-level fallback keeps the archive usable
        if log is not None:
            log.append(f"member-fallback {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------- text / binary
def h_text(data, name, R, depth, log):
    new = R.replace_text(data)
    if new is data:
        return None
    if len(new) != len(data):
        raise Unsafe("length changed")
    return new


def h_binary(data, name, R, depth, log):
    new = R.replace_binary(data)
    if new is data:
        return None
    if len(new) != len(data):
        raise Unsafe("length changed")
    return new


def h_ole(data, name, R, depth, log):
    """Edit stream contents in place (same size); directory entries and FAT are never touched."""
    import olefile
    fp = io.BytesIO(data)
    ole = olefile.OleFileIO(fp, write_mode=True)
    Ra = getattr(R, "ole_all", R)
    Rp = getattr(R, "ole_prop", Ra)
    umap = getattr(R, "unicode_map", {})
    changed = False
    expected = {}
    local_pairs = {}  # orig_bytes (ascii/utf8) -> pseudo_bytes replaced in THIS file's propsets
    streams = ole.listdir(streams=True, storages=False)
    is_prop = lambda p: p[-1].startswith("\x05") or p[-1] == "ISolidWorksInformation"
    # Pass 1: property-set streams first so we know this file's exact saved-account / author pairs
    prop_paths = [p for p in streams if is_prop(p)]
    other_paths = [p for p in streams if not is_prop(p)]
    for path in prop_paths:
        raw = ole.openstream(path).read()
        nb = _propset(raw, Rp, umap, local_pairs)
        expected["/".join(path)] = nb
        if nb is not raw:
            ole.write_stream(path, nb)
            changed = True
    # Pass 2: all other streams — global ole_all + per-file saved-account sweep + SolidWorks __ZLB
    for path in other_paths:
        raw = ole.openstream(path).read()
        pname = "/".join(path)
        # Never touch embedded raster/metafile preview images (keeps OLE preview consistency 25/25)
        if path[-1].lower() in ("preview", "previewpng", "thumbnail") or raw[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xd7\xcd\xc6\x9a") or raw[:2] == b"BM":
            expected[pname] = raw
            continue
        if path[-1].endswith("__ZLB"):
            nb = _zlb_stream(raw, Ra, Rp, local_pairs)
        else:
            nb = Ra.replace_binary(raw)
            if local_pairs:
                nb2 = _sweep_ole_stream(nb, local_pairs, Rp)
                if nb2 is not nb:
                    nb = nb2
        expected[pname] = nb
        if nb is not raw:
            ole.write_stream(path, nb)
            changed = True
    stale = Ra.replace_binary(data) is not data  # identifiers left in free/slack sectors
    if not stale and local_pairs:
        low_data = data.lower()
        for ob in local_pairs:
            if len(ob) >= 3 and ob.lower() in low_data:
                stale = True
                break
    if not changed and not stale:
        return None
    buf = bytearray(fp.getvalue())
    if stale:
        _ole_zero_unused(ole, buf)
    new = bytes(buf)
    before = olefile.OleFileIO(data)
    after = olefile.OleFileIO(new)
    if before.listdir(streams=True, storages=True) != after.listdir(streams=True, storages=True):
        raise Unsafe("OLE directory changed")
    for path, want in expected.items():
        if after.openstream(path).read() != want:
            raise Unsafe("OLE stream content mismatch")
    return new


def _zlb_stream(raw, Ra, Rp, local_pairs):
    """Clean SolidWorks *__ZLB streams in-place: 16B GUID + uint32 ulen + uint32 clen + zlib + 0-pad.

    SolidWorks uses zlib level 1; recompressing at level 9 fits within the original buffer
    so OLE stream size and FAT stay untouched. Verifies exact decompression before returning.
    """
    if len(raw) < 32 or raw[24:25] != b"\x78":
        return raw
    ulen, clen = struct.unpack_from("<II", raw, 16)
    if clen < 8 or 24 + clen > len(raw):
        return raw
    try:
        dec = zlib.decompress(raw[24:24 + clen])
    except Exception:
        return raw
    if len(dec) != ulen:
        return raw
    nb = Ra.replace_binary(dec)
    if local_pairs:
        nb2 = _sweep_ole_stream(nb, local_pairs, Rp)
        if nb2 is not nb:
            nb = nb2
    if nb is dec or len(nb) != ulen:
        return raw
    # Recompress at level 9; must fit in original stream leaving at least 8 zero trailer bytes (or exact fit)
    z9 = zlib.compress(nb, 9)
    max_z = len(raw) - 24
    if len(z9) > max_z:
        return raw
    out = raw[:20] + struct.pack("<I", len(z9)) + z9 + bytes(max_z - len(z9))
    if len(out) != len(raw):
        return raw
    try:
        if zlib.decompress(out[24:24 + len(z9)]) != nb:
            return raw
    except Exception:
        return raw
    return out


def _sweep_ole_stream(raw, local_pairs, R):
    """Replace this file's own saved-account/author values across its non-property streams."""
    from .pseudo import apply_case
    buf = None
    for ob, pb in sorted(local_pairs.items(), key=lambda t: -len(t[0])):
        if len(ob) < 3 or len(ob) != len(pb):
            continue
        # ASCII / UTF-8 exact byte-length occurrences (word-bounded when ASCII, except len>=5 in MC=/path)
        cur = bytes(buf) if buf is not None else raw
        ob_low = ob.lower()
        if ob_low in cur.lower():
            pat = re.compile(re.escape(ob), re.I)
            for m in pat.finditer(cur):
                s, e = m.start(), m.end()
                if ob.isascii() and not R._boundary(cur, s, e):
                    # Allow glued machine-name prefix like MC=ENGRNASIR; when len(ob) >= 5 and followed by boundary
                    after_ok = e >= len(cur) or not (cur[e] in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
                    if not (len(ob) >= 5 and after_ok):
                        continue
                rep = apply_case(cur[s:e], pb.decode("ascii")) if (ob.isascii() and pb.isascii()) else pb
                if len(rep) == e - s:
                    buf = buf or bytearray(raw)
                    buf[s:e] = rep
        # UTF-16LE occurrences
        if ob.isascii() and pb.isascii():
            u_ob = ob.decode("ascii").encode("utf-16-le")
            u_pb = pb.decode("ascii").encode("utf-16-le")
        else:
            s_ob = None
            for enc_u in ("utf-8", "latin-1"):
                try:
                    s_ob = ob.decode(enc_u)
                    break
                except UnicodeDecodeError:
                    continue
            if not s_ob or not pb.isascii():
                continue
            s_pb = pb.decode("ascii")
            s_pb = s_pb[:len(s_ob)] if len(s_pb) >= len(s_ob) else s_pb + "x" * (len(s_ob) - len(s_pb))
            u_ob = s_ob.encode("utf-16-le")
            u_pb = s_pb.encode("utf-16-le")
        cur = bytes(buf) if buf is not None else raw
        if u_ob.lower() in cur.lower():
            pat = re.compile(re.escape(u_ob), re.I)
            for m in pat.finditer(cur):
                s, e = m.start(), m.end()
                if e - s == len(u_pb):
                    if ob.isascii():
                        # check UTF-16LE word boundaries (allow glued suffix when len>=5)
                        after_bad = e + 2 <= len(cur) and cur[e + 1] == 0 and cur[e] in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
                        before_bad = s >= 2 and cur[s - 1] == 0 and cur[s - 2] in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
                        if after_bad or (before_bad and len(ob) < 5):
                            continue
                    rep_u = apply_case(cur[s:e:2], pb.decode("ascii")).decode("ascii").encode("utf-16-le") if (ob.isascii() and pb.isascii()) else u_pb
                    if len(rep_u) == e - s:
                        buf = buf or bytearray(raw)
                        buf[s:e] = rep_u
    return raw if buf is None else bytes(buf)


def _propset(raw, R, umap=None, local_pairs=None):
    """Property-set stream: every VT_LPSTR / VT_LPWSTR value (ASCII + non-ASCII), plus long runs."""
    buf = bytearray(R.replace_binary(raw))
    umap = umap or {}
    for m in re.finditer(rb"[\x1e\x1f]\x00\x00\x00", raw):
        o, wide = m.end(), raw[m.start()] == 0x1F
        if o + 4 > len(raw):
            continue
        n = int.from_bytes(raw[o:o + 4], "little") * (2 if wide else 1)
        if not 1 <= n <= 1024 or o + 4 + n > len(raw):
            continue
        s = raw[o + 4:o + 4 + n]
        if wide:
            if len(s) % 2:
                continue
            v = s.decode("utf-16-le", "replace").split("\x00", 1)[0]
            if not v:
                continue
            if all(0x20 <= ord(c) <= 0x7E for c in v):
                vb = v.encode("ascii")
                nv = R.replace_bytes(vb)
                if nv is not vb and nv != vb:
                    buf[o + 4:o + 4 + 2 * len(v)] = nv.decode("ascii").encode("utf-16-le")
                    if local_pairs is not None and len(vb) >= 3:
                        local_pairs[vb] = nv
            else:
                rep = umap.get(v.lower())
                if rep and rep.isascii():
                    # fit exact UTF-16LE character length of v
                    rfit = (rep[:len(v)] if len(rep) >= len(v) else rep + "x" * (len(v) - len(rep)))
                    if len(rfit) == len(v):
                        buf[o + 4:o + 4 + 2 * len(v)] = rfit.encode("utf-16-le")
                        if local_pairs is not None and len(v) >= 3:
                            for enc_u in ("utf-8", "latin-1"):
                                try:
                                    vb = v.encode(enc_u)
                                except UnicodeEncodeError:
                                    continue
                                rfb = (rep[:len(vb)] if len(rep) >= len(vb) else rep + "x" * (len(vb) - len(rep))).encode("ascii")
                                local_pairs[vb] = rfb
                else:
                    # Non-ASCII substring inside UTF-16LE path (e.g. C:\Users\séba\Desktop\...)
                    nv = v
                    for uk, urep in umap.items():
                        if not urep.isascii() or len(uk) < 3 or uk not in nv.lower():
                            continue
                        rfit = urep[:len(uk)] if len(urep) >= len(uk) else urep + "x" * (len(uk) - len(urep))
                        nv = re.sub(re.escape(uk), rfit, nv, flags=re.I)
                    if nv != v and len(nv) == len(v):
                        buf[o + 4:o + 4 + 2 * len(v)] = nv.encode("utf-16-le")
        else:
            v = s.split(b"\x00", 1)[0]
            if not v:
                continue
            if all(0x20 <= c <= 0x7E for c in v):
                nv = R.replace_bytes(v)
                if nv is not v and nv != v:
                    buf[o + 4:o + 4 + len(v)] = nv
                    if local_pairs is not None and len(v) >= 3:
                        local_pairs[v] = nv
            else:
                try:
                    vs = v.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        vs = v.decode("latin-1")
                    except Exception:
                        continue
                rep = umap.get(vs.lower())
                if rep and rep.isascii():
                    rfit = (rep[:len(v)] if len(rep) >= len(v) else rep + "x" * (len(v) - len(rep))).encode("ascii")
                    if len(rfit) == len(v):
                        buf[o + 4:o + 4 + len(v)] = rfit
                        if local_pairs is not None and len(v) >= 3:
                            local_pairs[v] = rfit
                else:
                    # Handle non-ASCII account embedded inside a Windows path (e.g. C:\Users\séba\Desktop\...)
                    cur_v = bytearray(v)
                    changed_v = False
                    for uk, urep in umap.items():
                        if not urep.isascii() or len(uk) < 3:
                            continue
                        for enc_u in ("utf-8", "latin-1"):
                            try:
                                ukb = uk.encode(enc_u)
                            except UnicodeEncodeError:
                                continue
                            if ukb in bytes(cur_v).lower():
                                rfit = (urep[:len(ukb)] if len(urep) >= len(ukb) else urep + "x" * (len(ukb) - len(urep))).encode("ascii")
                                for mm in re.finditer(re.escape(ukb), bytes(cur_v), re.I):
                                    cur_v[mm.start():mm.end()] = rfit
                                    changed_v = True
                    if changed_v and len(cur_v) == len(v):
                        buf[o + 4:o + 4 + len(v)] = bytes(cur_v)
    out = bytes(buf)
    return raw if out == raw else out


def _ole_zero_unused(ole, buf):
    """Zero free sectors, free mini-sectors and the slack after each stream's last sector."""
    import olefile
    FREE, END = olefile.FREESECT, olefile.ENDOFCHAIN
    ss, fat = ole.sectorsize, ole.fat
    zero = lambda off, n: buf.__setitem__(slice(off, off + n), bytes(n)) if 0 < off and off + n <= len(buf) else None

    def chain(start, table):
        out, s = [], start
        while s not in (FREE, END) and s < len(table) and len(out) <= len(table):
            out.append(s)
            s = table[s]
        return out

    for i, nxt in enumerate(fat):
        if nxt == FREE:
            zero((i + 1) * ss, ss)
    root = ole.root
    mini_secs = chain(root.isectStart, fat)
    if ole.minifat is None and root.size:
        ole.loadminifat()
    minifat = ole.minifat if ole.minifat is not None else []
    mss = ole.minisectorsize

    def mini_off(j):
        pos = j * mss
        k = pos // ss
        return (mini_secs[k] + 1) * ss + pos % ss if k < len(mini_secs) else -1

    for j, nxt in enumerate(minifat):
        if nxt == FREE:
            zero(mini_off(j), mss)
    for e in ole.direntries:
        if e is None or e.entry_type != olefile.STGTY_STREAM or not e.size:
            continue
        if e.size < ole.minisectorcutoff:
            secs = chain(e.isectStart, minifat)
            tail = e.size % mss
            if secs and tail:
                zero(mini_off(secs[-1]) + tail, mss - tail)
        else:
            secs = chain(e.isectStart, fat)
            tail = e.size % ss
            if secs and tail:
                zero((secs[-1] + 1) * ss + tail, ss - tail)


def h_sqlite(data, name, R, depth, log):
    """Rewrite text cells through SQL (byte edits would break index order), then REINDEX."""
    import sqlite3
    if not R.hits(data, min_len=4) and not any(R.hits(m.group()) for m in SQLITE_TEXT.finditer(data)):
        return None
    con = sqlite3.connect(":memory:")
    try:
        con.deserialize(data)
        was_ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
        if any((sql or "").upper().startswith("CREATE VIRTUAL") for _, sql in tables):
            raise Unsafe("sqlite virtual tables (FTS) not supported")
        con.create_function("deid", 1, lambda v: R.replace_str(v) if isinstance(v, str) else v,
                            deterministic=True)
        changed = 0
        for t, _ in tables:
            if t.startswith("sqlite_"):
                continue
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
            for c in cols:
                cur = con.execute(f'UPDATE "{t}" SET "{c}" = deid("{c}") '
                                  f'WHERE typeof("{c}") = \'text\' AND deid("{c}") != "{c}"')
                changed += cur.rowcount
        if not changed:
            return None
        con.commit()
        con.execute("REINDEX")
        con.commit()
        con.execute("VACUUM")  # drops free pages that still hold the old text
        if was_ok and con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Unsafe("sqlite integrity_check failed")
        return con.serialize()
    finally:
        con.close()


def h_stl(data, name, R, depth, log):
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if 84 + 50 * n == len(data):  # binary STL: only the 80-byte header is text
            hdr = R.replace_bytes(data[:80])
            return None if hdr is data[:80] or hdr == data[:80] else hdr + data[80:]
    return h_text(data, name, R, depth, log)


# ---------------------------------------------------------------- images (metadata only)
def h_image(data, name, R, depth, log):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return _png(data, R)
    if data[:3] == b"\xff\xd8\xff":
        return _jpeg(data, R)
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return h_binary(data, name, R, depth, log)
    return None


def _png(data, R):
    out, pos, changed = [data[:8]], 8, False
    while pos < len(data):
        if pos + 8 > len(data):
            out.append(data[pos:])
            break
        ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + ln]
        chunk = data[pos:pos + 12 + ln]
        new_body = None
        if typ in (b"tEXt", b"iTXt"):
            if typ == b"iTXt":
                parts = body.split(b"\x00", 3)
                if len(parts) == 4 and parts[1][:1] == b"\x01":
                    kw, rest = parts[0], parts[3]
                    hdr = body[: len(body) - len(rest)]
                    i = rest.index(b"\x00") + 1 if b"\x00" in rest else 0
                    txt = zlib.decompress(rest[i:])
                    nt = R.replace_text(txt)
                    if nt is not txt:
                        new_body = hdr + rest[:i] + zlib.compress(nt)
                else:
                    nb = R.replace_text(body)
                    new_body = nb if nb is not body else None
            else:
                nb = R.replace_text(body)
                new_body = nb if nb is not body else None
        elif typ == b"zTXt":
            k = body.index(b"\x00")
            txt = zlib.decompress(body[k + 2:])
            nt = R.replace_text(txt)
            if nt is not txt:
                new_body = body[:k + 2] + zlib.compress(nt)
        elif typ == b"eXIf":
            nb = R.replace_binary(body)
            new_body = nb if nb is not body else None
        if new_body is not None:
            changed = True
            crc = zlib.crc32(typ + new_body) & 0xFFFFFFFF
            chunk = struct.pack(">I4s", len(new_body), typ) + new_body + struct.pack(">I", crc)
        out.append(chunk)
        pos += 12 + ln
        if typ == b"IEND":
            out.append(data[pos:])
            break
    if not changed:
        return None
    new = b"".join(out)
    _validate_image(new)
    return new


def _jpeg(data, R):
    buf, pos, changed = bytearray(data), 2, False
    while pos + 4 <= len(data) and data[pos] == 0xFF:
        marker = data[pos + 1]
        if marker == 0xDA or marker == 0xD9:  # start of scan: image data follows
            break
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            pos += 2
            continue
        ln = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        if 0xE0 <= marker <= 0xEF or marker == 0xFE:
            seg = data[pos + 4:pos + 2 + ln]
            new = R.replace_binary(seg) if marker != 0xFE else R.replace_bytes(seg)
            if new is not seg:
                buf[pos + 4:pos + 2 + ln] = new
                changed = True
        pos += 2 + ln
    if not changed:
        return None
    new = bytes(buf)
    _validate_image(new)
    return new


def _validate_image(b):
    from PIL import Image
    with Image.open(io.BytesIO(b)) as im:
        im.load()


# ---------------------------------------------------------------- PDF
def h_pdf(data, name, R, depth, log):
    import pikepdf
    pdf = pikepdf.open(io.BytesIO(data))
    npages = len(pdf.pages)
    Rpt = getattr(R, "pdf_text", R)
    Rpm = getattr(R, "pdf_meta", Rpt)
    changed = [False]

    def fix_str(v, meta_field=False):
        Rx = Rpm if meta_field else Rpt
        try:
            raw = bytes(v)
        except Exception:
            return None
        if raw.startswith(b"\xfe\xff"):
            s = raw[2:].decode("utf-16-be", "ignore")
            ns = Rx.replace_str(R.replace_unicode_str(s))
            return pikepdf.String(ns) if ns != s else None
        # Handle UTF-8 or Latin-1 non-ASCII PDF strings (e.g. Author = 'Jesús', 'Séba')
        if not raw.isascii():
            try:
                s = raw.decode("utf-8")
            except UnicodeDecodeError:
                s = raw.decode("latin-1")
            ns = Rx.replace_str(R.replace_unicode_str(s))
            if ns != s:
                return pikepdf.String(ns)
        nb = Rx.replace_bytes(raw)
        return pikepdf.String(nb) if nb is not raw else None

    def walk(obj, d=0):
        if d > 6:
            return
        if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
            for k in list(obj.keys()):
                if k in ("/Parent", "/P", "/Kids", "/Contents", "/Font", "/Resources"):
                    continue
                v = obj.get(k)
                mf = k in ("/Author", "/Creator", "/Subject", "/Keywords")
                if isinstance(v, pikepdf.String):
                    nv = fix_str(v, meta_field=mf)
                    if nv is not None:
                        obj[k] = nv
                        changed[0] = True
                elif isinstance(v, (pikepdf.Dictionary, pikepdf.Array)) and not v.is_indirect:
                    walk(v, d + 1)
        elif isinstance(obj, pikepdf.Array):
            for i, v in enumerate(list(obj)):
                if isinstance(v, pikepdf.String):
                    nv = fix_str(v)
                    if nv is not None:
                        obj[i] = nv
                        changed[0] = True
                elif isinstance(v, (pikepdf.Dictionary, pikepdf.Array)) and not v.is_indirect:
                    walk(v, d + 1)

    for obj in pdf.objects:
        walk(obj)
        if isinstance(obj, pikepdf.Stream):
            t = obj.get("/Type")
            if t == "/Metadata":
                raw = obj.read_bytes()
                try:
                    s = raw.decode("utf-8")
                    s2 = R.replace_unicode_str(s)
                    b2 = s2.encode("utf-8") if s2 != s else raw
                except UnicodeDecodeError:
                    b2 = raw
                nb = Rpm.replace_text(b2)
                if nb != raw:
                    obj.write(nb)
                    changed[0] = True
            elif t == "/EmbeddedFile":
                raw = obj.read_bytes()
                nb = _safe_member(raw, "embedded.bin", R, depth, log)
                if nb is not None:
                    obj.write(nb)
                    changed[0] = True
    walk(pdf.trailer)
    new = None
    if changed[0]:
        out = io.BytesIO()
        pdf.save(out, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.preserve,
                 deterministic_id=True)
        new = out.getvalue()
    paged = _pdf_page_text(new if new is not None else data, R)
    if paged is not None:
        new = paged
    if new is None:
        return None
    with pikepdf.open(io.BytesIO(new)) as chk:
        if len(chk.pages) != npages:
            raise Unsafe("page count changed")
    return new


def _pdf_page_text(data, R):
    """Visible page text: redact each identifier (ASCII + non-ASCII) and write its pseudonym
    at the exact oriented bounding box (handling horizontal, rotated, and vertical text)."""
    import pymupdf
    from .pseudo import apply_case
    Rpt = getattr(R, "pdf_text", R)
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.needs_pass:
        return None
    changed = False
    for page in doc:
        text = page.get_text()
        if not text:
            continue
        b = text.encode("utf-8", "surrogateescape")
        hs = Rpt.hits(b)
        uhs = R.unicode_hits(text)
        if not hs and not uhs:
            continue
        reps = {}
        for orig, rep in uhs:
            reps[orig] = rep
        for s, e, p in hs:
            try:
                orig = b[s:e].decode("utf-8")
                if orig not in reps:
                    reps[orig] = apply_case(b[s:e], p).decode("ascii")
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
        writes = []
        claimed = []
        missed = []
        for orig, rep in sorted(reps.items(), key=lambda t: -len(t[0])):
            is_asc = orig.isascii()
            hit_any = False
            for q in page.search_for(orig, quads=True):
                r = q.rect
                if r.is_empty or r.width <= 0 or r.height <= 0:
                    continue
                # Skip if already covered by a longer match
                if any((r & c).get_area() > 0.5 * r.get_area() for c in claimed):
                    hit_any = True
                    continue
                dx, dy = q.ur.x - q.ul.x, q.ur.y - q.ul.y
                horiz = abs(dx) >= abs(dy)
                if is_asc:
                    if horiz:
                        cw = r.width / max(1, len(orig))
                        ctx_r = pymupdf.Rect(r.x0 - 1.5 * cw, r.y0 - 0.1 * r.height,
                                             r.x1 + 1.5 * cw, r.y1 + 0.1 * r.height)
                    else:
                        ch = r.height / max(1, len(orig))
                        ctx_r = pymupdf.Rect(r.x0 - 0.1 * r.width, r.y0 - 1.5 * ch,
                                             r.x1 + 0.1 * r.width, r.y1 + 1.5 * ch)
                    ctx = page.get_textbox(ctx_r).replace("\n", " ").encode("utf-8", "ignore")
                    ob = orig.encode("utf-8", "ignore")
                    matches = list(re.finditer(re.escape(ob), ctx, re.I))
                    if not matches or not any(Rpt._boundary(ctx, m.start(), m.end()) for m in matches):
                        continue  # match inside a longer non-boundary word or PyMuPDF ligature-offset bug
                if horiz:
                    core = pymupdf.Rect(r.x0 + 0.01 * r.width, r.y0 + 0.15 * r.height,
                                        r.x1 - 0.01 * r.width, r.y1 - 0.15 * r.height)
                    fs = max(2.0, min(r.height * 0.72, r.width / max(1, len(rep)) / 0.54))
                    ang = 0 if dx >= 0 else 180
                    pt = pymupdf.Point(r.x0, r.y1 - 0.22 * r.height) if ang == 0 else pymupdf.Point(r.x1, r.y0 + 0.22 * r.height)
                else:
                    core = pymupdf.Rect(r.x0 + 0.15 * r.width, r.y0 + 0.01 * r.height,
                                        r.x1 - 0.15 * r.width, r.y1 - 0.01 * r.height)
                    fs = max(2.0, min(r.width * 0.72, r.height / max(1, len(rep)) / 0.54))
                    ang = 90 if dy < 0 else 270
                    pt = pymupdf.Point(r.x1 - 0.22 * r.width, r.y1) if ang == 90 else pymupdf.Point(r.x0 + 0.22 * r.width, r.y0)
                page.add_redact_annot(core, fill=False, cross_out=False)
                writes.append((pt, rep, fs, ang))
                claimed.append(r)
                hit_any = True
            if not hit_any:
                missed.append(orig.lower())
        # Span-level fallback ONLY for hits search_for missed (e.g. fi/fl/ff ligatures)
        if missed:
            for blk in page.get_text("dict").get("blocks", ()):
                for ln in blk.get("lines", ()):
                    ldx, ldy = ln.get("dir", (1.0, 0.0))
                    lhoriz = abs(ldx) >= abs(ldy)
                    for sp in ln.get("spans", ()):
                        st = sp.get("text", "")
                        if len(st) < 3:
                            continue
                        stl = st.lower()
                        if not any(m in stl for m in missed):
                            continue
                        r = pymupdf.Rect(sp["bbox"])
                        if r.is_empty or r.width <= 0 or r.height <= 0:
                            continue
                        if any((r & c).get_area() > 0.3 * min(r.get_area(), c.get_area()) for c in claimed):
                            continue
                        st2 = R.replace_unicode_str(st)
                        st3 = Rpt.replace_str(st2)
                        if st3 == st:
                            continue
                        if lhoriz:
                            core = pymupdf.Rect(r.x0 + 0.01 * r.width, r.y0 + 0.15 * r.height,
                                                r.x1 - 0.01 * r.width, r.y1 - 0.15 * r.height)
                            fs = max(2.0, min(r.height * 0.72, r.width / max(1, len(st3)) / 0.54))
                            ang = 0 if ldx >= 0 else 180
                            pt = pymupdf.Point(r.x0, r.y1 - 0.22 * r.height) if ang == 0 else pymupdf.Point(r.x1, r.y0 + 0.22 * r.height)
                        else:
                            core = pymupdf.Rect(r.x0 + 0.15 * r.width, r.y0 + 0.01 * r.height,
                                                r.x1 - 0.15 * r.width, r.y1 - 0.01 * r.height)
                            fs = max(2.0, min(r.width * 0.72, r.height / max(1, len(st3)) / 0.54))
                            ang = 90 if ldy < 0 else 270
                            pt = pymupdf.Point(r.x1 - 0.22 * r.width, r.y1) if ang == 90 else pymupdf.Point(r.x0 + 0.22 * r.width, r.y0)
                        page.add_redact_annot(core, fill=False, cross_out=False)
                        writes.append((pt, st3, fs, ang))
                        claimed.append(r)
        if writes:
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                  graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
            for pt, rep, fs, ang in writes:
                page.insert_text(pt, rep, fontsize=fs, fontname="helv", rotate=ang)
            changed = True
    if not changed:
        return None
    return doc.tobytes(garbage=1, deflate=True)


# ---------------------------------------------------------------- archives
def _zip(data, name, R, depth, log, rename):
    if depth >= C.MAX_ARCHIVE_DEPTH:
        return None
    zin = zipfile.ZipFile(io.BytesIO(data))
    infos = zin.infolist()
    if any(i.flag_bits & 0x1 for i in infos):
        raise Unsafe("encrypted zip")
    out = io.BytesIO()
    changed = False
    with zipfile.ZipFile(out, "w", allowZip64=True) as zout:
        for info in infos:
            nn = rename_member(info.filename, R) if rename else info.filename
            ni = zipfile.ZipInfo(nn, date_time=info.date_time)
            ni.compress_type = info.compress_type
            ni.external_attr = info.external_attr
            ni.create_system = info.create_system
            ni.comment = R.replace_bytes(info.comment)
            ni.extra = info.extra
            changed |= nn != info.filename or ni.comment != info.comment
            if info.is_dir():
                zout.writestr(ni, b"")
                continue
            raw = zin.read(info)
            new = _safe_member(raw, info.filename, R, depth, log)
            changed |= new is not None
            zout.writestr(ni, new if new is not None else raw)
        zout.comment = R.replace_bytes(zin.comment)
        changed |= zout.comment != zin.comment
    if not changed:
        return None
    res = out.getvalue()
    with zipfile.ZipFile(io.BytesIO(res)) as chk:
        if chk.testzip() is not None or len(chk.infolist()) != len(infos):
            raise Unsafe("zip validation failed")
    return res


def h_zip_archive(data, name, R, depth, log):
    return _zip(data, name, R, depth, log, rename=True)


def h_zip_container(data, name, R, depth, log):
    return _zip(data, name, R, depth, log, rename=False)


def _tar_mode(data):
    if data[:2] == b"\x1f\x8b":
        return "gz"
    if data[:3] == b"BZh":
        return "bz2"
    if data[:6] == b"\xfd7zXZ\x00":
        return "xz"
    return ""


def h_tar(data, name, R, depth, log):
    if depth >= C.MAX_ARCHIVE_DEPTH:
        return None
    comp = _tar_mode(data)
    tin = tarfile.open(fileobj=io.BytesIO(data), mode="r:" + comp if comp else "r:")
    out = io.BytesIO()
    changed = False
    members = tin.getmembers()
    with tarfile.open(fileobj=out, mode="w:" + comp if comp else "w", format=tin.format) as tout:
        for m in members:
            nm = rename_member(m.name, R)
            ti = tarfile.TarInfo(nm)
            for a in ("size", "mtime", "mode", "type", "uid", "gid", "devmajor", "devminor"):
                setattr(ti, a, getattr(m, a))
            ti.linkname = rename_member(m.linkname, R) if m.linkname else ""
            ti.uname, ti.gname = R.replace_str(m.uname or ""), R.replace_str(m.gname or "")
            changed |= (nm, ti.linkname, ti.uname, ti.gname) != (m.name, m.linkname, m.uname, m.gname)
            if m.isfile():
                raw = tin.extractfile(m).read()
                new = _safe_member(raw, m.name, R, depth, log)
                changed |= new is not None
                payload = new if new is not None else raw
                ti.size = len(payload)
                tout.addfile(ti, io.BytesIO(payload))
            else:
                tout.addfile(ti)
    if not changed:
        return None
    res = out.getvalue()
    with tarfile.open(fileobj=io.BytesIO(res), mode="r:*") as chk:
        if len(chk.getmembers()) != len(members):
            raise Unsafe("tar validation failed")
    return res


def h_gzip(data, name, R, depth, log):
    if depth >= C.MAX_ARCHIVE_DEPTH:
        return None
    inner_name = name[:-3] if name.lower().endswith(".gz") else name
    raw = gzip.decompress(data)
    new = _safe_member(raw, inner_name, R, depth, log)
    flg = data[3]
    has_name = bool(flg & 0x08)
    if new is None and not has_name:
        return None
    mtime = struct.unpack("<I", data[4:8])[0]
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=mtime) as g:
        g.write(new if new is not None else raw)
    res = out.getvalue()
    if gzip.decompress(res) != (new if new is not None else raw):
        raise Unsafe("gzip validation failed")
    return res


HANDLERS = {
    "text": h_text, "binary": h_binary, "ole": h_ole, "stl": h_stl, "image": h_image, "sqlite": h_sqlite,
    "pdf": h_pdf, "zip_archive": h_zip_archive, "zip_container": h_zip_container,
    "tar": h_tar, "gzip": h_gzip,
}
