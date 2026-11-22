import os
from pathlib import Path

DATA = Path(os.environ.get("DEID_DATA", "/data"))
INPUT = Path(os.environ.get("DEID_INPUT", DATA / "input"))
MANIFEST = Path(os.environ.get("DEID_MANIFEST", DATA / "manifest.tsv"))
# Everything under PRIVATE contains real identifiers: never upload, never commit.
PRIVATE = Path(os.environ.get("DEID_PRIVATE", DATA / "private"))
OUT = Path(os.environ.get("DEID_OUT", DATA / "out"))

BASE_URL = "https://machina-input.joinbuilders.org/"

TEXT_EXTS = {
    ".step", ".stp", ".p21", ".iges", ".igs", ".dxf", ".sat", ".svg", ".wrl", ".vrml",
    ".obj", ".mtl", ".ply", ".ps", ".eps", ".unv", ".x_t", ".xmt_txt", ".brep", ".neu",
    ".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".html", ".htm", ".yaml", ".yml",
    ".scad", ".gcode", ".ngc", ".nc", ".ini", ".cfg", ".kicad_pcb", ".kicad_sch",
    ".kicad_mod", ".kicad_pro", ".rst", ".tex", ".py", ".m", ".fea", ".rul", ".dat",
}
# Native binaries: length-preserving edits inside printable ASCII / UTF-16LE runs only.
BINARY_STRINGS_EXTS = {
    ".sldprt", ".sldasm", ".slddrw", ".prtdot", ".asmdot", ".drwdot", ".sldlfp",
    ".ipt", ".iam", ".idw", ".ipn", ".prt", ".asm", ".drw", ".par", ".psm", ".pwd",
    ".catpart", ".catproduct", ".catdrawing", ".x_b", ".xmt_bin", ".jt", ".3dm",
    ".u3d", ".sab", ".smt", ".f3d_part",
}
ZIP_ARCHIVE_EXTS = {".zip"}  # plain archives: member paths get renamed
ZIP_CONTAINER_EXTS = {".fcstd", ".fcstd1", ".3mf", ".f3d", ".f3z", ".docx", ".xlsx",
                      ".pptx", ".odt", ".ods", ".odg", ".kmz", ".dwfx", ".dwf"}
TAR_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
# No safe writer available yet: copied unchanged and listed in README.txt.
COPY_EXTS = {".dwg", ".z", ".rar", ".7z", ".exe", ".dll", ".gif", ".webp", ".bmp"}

# Binary-run safety: a run must be this long and mostly "texty" before we touch it,
# so random bytes in compressed/geometry payloads are never rewritten.
BIN_MIN_RUN = 8
BIN_LONG_RUN = 16  # shorter ASCII runs must be NUL-terminated
BIN_TEXTY_FRAC = 0.85

MAX_ARCHIVE_DEPTH = 4
FILE_TIMEOUT_S = 600
HARVEST_HEAD_TEXT = 4 << 20
HARVEST_HEAD_BIN = 32 << 20
