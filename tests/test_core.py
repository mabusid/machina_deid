"""Synthetic tests (no real data): python -m pytest -q tests  or  python tests/test_core.py"""
import gzip
import io
import os
import struct
import sys
import tarfile
import zipfile
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from deid.handlers import process  # noqa: E402
from deid.matcher import Replacer  # noqa: E402
from deid.paths import rename_rel  # noqa: E402
from deid.pseudo import Pseudonymizer  # noqa: E402
from deid.resolve import Builder  # noqa: E402


def build():
    B = Builder(Pseudonymizer(b"k" * 32, reserved={"john", "smith", "acmecorp", "zorblax"}), set())
    B.person("John Smith")
    B.email("j.smith@acmecorp.com")
    B.owner("Zorblax-Robotics")
    B.username("jsmith")
    R = Replacer(B.keys)
    R.owners = B.owners
    return B, R


def test_lengths_and_consistency():
    B, R = build()
    for k, v in B.keys.items():
        assert len(k) == len(v) and k != v
    s = b"Drawn by John Smith / J. Smith / SMITH, JOHN / jsmith / j.smith@acmecorp.com"
    out = R.replace_bytes(s)
    assert len(out) == len(s)
    low = out.lower()
    for w in (b"john", b"smith", b"acmecorp"):
        assert w not in low, out
    # same person -> same surname pseudonym in every variant
    pl = B.keys["smith"] if "smith" in B.keys else B.keys["john smith"].split(" ")[1]
    assert out.lower().count(pl.encode()) >= 3, out


def test_boundaries():
    _, R = build()
    assert R.replace_bytes(b"blacksmithing") == b"blacksmithing"
    assert R.replace_bytes(b"ZorblaxRobotics_v2").lower() != b"zorblaxrobotics_v2"
    assert R.replace_bytes(b"part_zorblax2.step")[:5] == b"part_"


def test_paths():
    _, R = build()
    rel = "sources/github/Zorblax-Robotics__arm/jsmith_bracket.SLDPRT"
    new = rename_rel(rel, R)
    assert new.startswith("sources/github/") and new.endswith("_bracket.SLDPRT")
    assert "zorblax" not in new.lower() and "jsmith" not in new.lower()
    assert len(new) == len(rel)


def test_step_text():
    _, R = build()
    step = (b"ISO-10303-21;\nHEADER;\nFILE_NAME('C:\\\\Users\\\\jsmith\\\\a.step','2020',('John Smith'),"
            b"('Zorblax Robotics'),'x','SolidWorks','');\nENDSEC;\nDATA;\n#1=CARTESIAN_POINT('',(1.,2.,3.));\nENDSEC;\nEND-ISO-10303-21;\n")
    new, kind = process(step, "a.step", R)
    assert kind == "text" and len(new) == len(step)
    assert b"jsmith" not in new.lower() and b"zorblax" not in new.lower()
    assert b"CARTESIAN_POINT('',(1.,2.,3.))" in new


def test_binary_stl_header_only():
    _, R = build()
    hdr = b"solid made by jsmith at Zorblax Robotics".ljust(80, b" ")
    tri = struct.pack("<12fH", *([0.0] * 12), 0)
    data = hdr + struct.pack("<I", 1) + tri
    new, kind = process(data, "x.stl", R)
    assert kind == "stl" and new[80:] == data[80:] and b"jsmith" not in new.lower()


def test_zip_tar_gzip():
    _, R = build()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Zorblax-Robotics-main/jsmith.step", b"ISO-10303-21;\n/* John Smith */\n")
        z.writestr("Zorblax-Robotics-main/readme.txt", b"contact j.smith@acmecorp.com")
    new, kind = process(buf.getvalue(), "repo.zip", R)
    names = zipfile.ZipFile(io.BytesIO(new)).namelist()
    assert kind == "zip_archive" and not any("jsmith" in n.lower() or "zorblax" in n.lower() for n in names)

    tb = io.BytesIO()
    with tarfile.open(fileobj=tb, mode="w:gz") as t:
        payload = b"author: John Smith"
        ti = tarfile.TarInfo("jsmith/notes.txt")
        ti.size = len(payload)
        ti.uname = "jsmith"
        t.addfile(ti, io.BytesIO(payload))
    new, kind = process(tb.getvalue(), "a.tar.gz", R)
    with tarfile.open(fileobj=io.BytesIO(new), mode="r:gz") as t:
        m = t.getmembers()[0]
        assert "jsmith" not in m.name and m.uname != "jsmith"
        assert b"smith" not in t.extractfile(m).read().lower()

    g = gzip.compress(b"John Smith wrote this")
    new, kind = process(g, "x.unv.gz", R)
    assert kind == "gzip" and b"smith" not in gzip.decompress(new).lower()


def test_png_text_chunk():
    _, R = build()

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"tEXt", b"Author\x00John Smith")
           + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"IEND", b""))
    new, kind = process(png, "a.png", R)
    assert kind == "image" and b"Smith" not in new


def test_pdf_metadata():
    import pikepdf
    _, R = build()
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Author"] = "John Smith"
    pdf.docinfo["/Title"] = "Zorblax Robotics bracket"
    b = io.BytesIO()
    pdf.save(b)
    new, kind = process(b.getvalue(), "d.pdf", R)
    with pikepdf.open(io.BytesIO(new)) as p:
        assert "Smith" not in str(p.docinfo["/Author"]) and "Zorblax" not in str(p.docinfo["/Title"])
        assert len(p.pages) == 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
