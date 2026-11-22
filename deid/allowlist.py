"""Tokens that must never be pseudonymized, and the common-word dictionary."""
import functools
from pathlib import Path

_RAW = """
iso 10303 header endsec data entities entity solid endsolid facet loop vertex outer normal
step stp iges igs dxf dwg sat sab stl obj wrl vrml svg pdf png jpg jpeg tif tiff zip tar gz
sldprt sldasm slddrw ipt iam idw ipn prt asm drw par psm catpart catproduct jt brep fcstd
3mf f3d f3z x_t x_b xmt txt md csv json xml html yaml extracted master main src docs doc
sources github gitlab catalog web existing archives files file parts part assembly assemblies
drawings drawing models model cad stl step_files native export exports release releases rev
ansi asme din astm sae nema ieee mil rohs jis bs en gost gb ul csa ce fcc nist
aluminum aluminium steel stainless titanium brass bronze copper abs pla petg delrin nylon
acetal polycarbonate acrylic rubber silicone carbon fiber
mm cm inch inches deg rad metric imperial
bolt bolts nut nuts washer washers screw screws bearing bearings oring gear gears spring
hex socket cap head flat pan button shaft motor bracket plate base cover housing frame
inc llc ltd gmbh corp co company corporation limited ag sa bv srl spa plc kg oy ab
com org net edu gov io de uk ac fr it es nl jp cn ru br in au ca ch se dk no fi pl cz
www http https ftp mailto localhost
gmail googlemail yahoo hotmail outlook live msn icloud me aol protonmail gmx qq
w3 xmlns purl adobe creativecommons sodipodi inkscape schema schemas
freecad solidworks dassault autodesk inventor fusion fusion360 onshape openscad kicad
blender catia creo ptc siemens nx rhino sketchup librecad solidedge spaceclaim ansys
parasolid acis spatial opencascade occt cadquery salome gmsh meshlab cura prusaslicer
microsoft windows linux macos apple google amazon mozilla python java
unknown none null default user users admin administrator owner author public guest
test sample example demo temp tmp new copy final draft
info sales support contact hello office mail email webmaster team help service noreply
desktop laptop dropbox onedrive gdrive documents downloads pictures appdata roaming local
online website internet software hardware firmware download upload setup config readme
robot robotics drone arduino raspberry printer printing slicer filament nozzle extruder
hotend pcb gerber bom cnc lathe mill milling router laser makerspace hackerspace fablab
github gitlab bitbucket youtube thingiverse printables grabcad instructables wiki
multi mini micro nano mega ultra pro max plus lite basic standard custom generic
open opensource libre free hardware styles objects machining manufacturing fabrication
"""
ALLOW = frozenset(_RAW.split())

PLACEHOLDER_VALUES = frozenset("""
unknown none null n/a na nil user users admin administrator owner author default
guest public anonymous everyone system root test sample example name your name
solidworks autodesk freecad inventor fusion onshape kicad microsoft windows
""".split()) | {"your name", "first last", "john doe", "jane doe"}


@functools.lru_cache(maxsize=1)
def common_words() -> frozenset:
    """Lowercase dictionary words (proper nouns excluded, so surnames stay distinctive)."""
    words = set()
    for p in ("/usr/share/dict/words", "/usr/share/dict/american-english"):
        f = Path(p)
        if f.exists():
            for w in f.read_text(errors="ignore").split():
                if w.islower() and w.isalpha():
                    words.add(w)
    return frozenset(words)


def is_common(token: str) -> bool:
    """Dictionary word, allowlisted, or an inflection of one (old word lists lack plurals)."""
    t = token.lower()
    w = common_words()
    if t in ALLOW or t in w:
        return True
    stems = []
    if t.endswith("ies"):
        stems.append(t[:-3] + "y")
    if t.endswith("es"):
        stems.append(t[:-2])
    if t.endswith("s"):
        stems.append(t[:-1])
    if t.endswith("ed"):
        stems += [t[:-2], t[:-1]]
    if t.endswith("ing"):
        stems += [t[:-3], t[:-3] + "e"]
    if t.endswith(("er", "ly")):
        stems.append(t[:-2])
    return any(s in w or s in ALLOW for s in stems if len(s) >= 3)
