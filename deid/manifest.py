from dataclasses import dataclass
from pathlib import Path


@dataclass
class Row:
    rel: str
    size: int
    md5: str
    url: str


def load_manifest(path) -> list[Row]:
    rows = []
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        p = line.rstrip("\n").split("\t")
        rows.append(Row(p[0], int(p[1]), p[2] if len(p) > 2 else "", p[3] if len(p) > 3 else p[0]))
    return rows


def present(rows, input_root):
    root = Path(input_root)
    for r in rows:
        p = root / r.rel
        if p.is_file():
            yield r, p


def unique_present(rows, input_root):
    """One (rel, path) per distinct content (manifest md5; blank md5 = always unique)."""
    seen = set()
    for r, p in present(rows, input_root):
        key = (r.md5, r.size) if r.md5 else r.rel
        if key in seen:
            continue
        seen.add(key)
        yield r.rel, p
