"""Path renaming: identifying segments only; extensions, depth and generic folders kept."""
import os
import re

_MULTI_EXT = re.compile(r"(\.(?:tar\.gz|tar\.bz2|tar\.xz|[A-Za-z0-9_]+\.\d+)|\.[^./]+)$")


def split_ext(name: str):
    m = _MULTI_EXT.search(name)
    if not m or m.start() == 0:
        return name, ""
    return name[: m.start()], m.group(1)


def _segment(seg: str, R) -> str:
    owners = getattr(R, "owners", {})
    if "__" in seg:
        parts = seg.split("__")
        out = []
        for p in parts:
            o = owners.get(p) or owners.get(p.lower())
            out.append(o if o else R.replace_str(p))
        return "__".join(out)
    return R.replace_str(seg)


def rename_rel(rel: str, R) -> str:
    """Rename one relative path ('/'-separated). Length of each segment is preserved."""
    parts = rel.split("/")
    out = [_segment(p, R) for p in parts[:-1]]
    stem, ext = split_ext(parts[-1])
    out.append(_segment(stem, R) + ext)
    return "/".join(out)


def rename_member(name: str, R) -> str:
    """Archive member names may use either separator."""
    if "\\" in name and "/" not in name:
        return rename_rel(name.replace("\\", "/"), R).replace("/", "\\")
    trail = name.endswith("/")
    new = rename_rel(name.rstrip("/"), R) if name.rstrip("/") else name
    return new + ("/" if trail and not new.endswith("/") else "")


def ext_of(name: str) -> str:
    n = name.lower()
    for suf in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if n.endswith(suf):
            return suf
    ext = os.path.splitext(n)[1]
    if re.fullmatch(r"\.\d+", ext):  # Creo versioned files: part.prt.3
        inner = os.path.splitext(n[: -len(ext)])[1]
        return inner or ext
    return ext
