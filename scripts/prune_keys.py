"""Write PRIVATE/exclude.txt: mapping keys that are generic terms rather than identities.

Inputs: PRIVATE/mapping.json (unpruned) and PRIVATE/key_spread.tsv (scripts/key_spread.py).
Rules: initials-only variants, all 3-character keys, 4-character keys that are not first
names, keys hitting in >= --max-repos unrelated repos (unless person-like or in KEEP),
vendor/boilerplate phrases, and the MANUAL list. Re-run deid.resolve afterwards.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deid import config as C  # noqa: E402

NAMES4 = set("""adam alan alex andy anne aron ayad beni bert beth carl chen dave doug emre
eric erik esra ewen fran frey gonz greg hans igor ivan jake jane jean jeff jens joan joel
jose juan judy karl kent koch koop kurt kyle lale lars leon lisa luis luke marc mary mika
milo neil olav onur paul pete phil qian rafa rafi remy rene rory rosa ross ruiz ryan sean
seth syed todd ugur wang wong xing yann zack""".split())

KEEP = set("""epallares jolles bpoll pcorreia dlevin marco fundaciocim bcn3d source-robotics
sourcerobotics stiima binaryblackhole mechpc locilamp""".split())

BOILER = re.compile(r"rights reserved|licen[cs]e|corporation|incorporated|\binc\b|company|"
                    r"systems|notices|oracle|ljava|all users|authori[sz]|tools|cascade|"
                    r"datavision|supply|partsolutions|stepup|\bmcad\b|header|holders?\b|"
                    r"liable|the authors|notice and|\bgmbh\b|foundation|division|windows user|"
                    r"copier user")
# label_person values (text after "Drawn by" etc.) must look like "First [M.] Last"
LABEL_NAME = re.compile(r"[A-Z][a-z'\-]+(?: [A-Z]\.?)?(?: [A-Z][a-z'\-]+){1,2}")

MANUAL = set("""glovebox esquisse croquis direccional carpeta autor punto redondeo
cortar-extruir saliente-extruir extruir chafl chapa cbore aleph boss.-extru. cnccmv thor
maxwell mise administrador texas matra-datavision baugruppe endcap junio solidwork caxa
optomechanical monotype rosca ancho plano incr datasheet potentiometer partst partstream
gimbal bluetooth buildusergr mycelium changer germany hamburg aarhus regex trillium docx
traceparts rockwell corel jetson cproject stepmaker matplotlib.org hackaday voron upesy etat
oper conc como cosm liste bitstream tegu alibre ezdxf easyeda matplotlib breadboard buildlog
ethernet freecadweb extru silkscreen boolean cthread pico utils noname phys december deps
mech cadf cadc pcbnew centre gripper engr soic chan params namespace robo broadcom todo
thorlabs misumi adafruit lulzbot reprap wuerth festo igus bourns cadenas raspberrypi
wiring coincidente volution v.\ mat.-extru. etude chanfrein ancrage productname trimesh
sparkfun prusa farnell nodemcu mendel huxley combiner ncidente coaxiale edgebend darwin
grblhal webui verisign usuario hwdev physcomp""".replace("\\ ", " ").split()) | {"cbore for", "vue de mise", "cosmetic thread", "corps volumiques",
                      "simple hole", "textcreation time", "an author", "tap drill for",
                      "raspberry pi", "solid bodies", "detail folder", "century gothic",
                      "v. mat.-extru.", "dossier de", "classeur de conception",
                      "ancrage de la", "chapa met", "rosca cosm", "filetage de per",
                      "open rail", "traceparts s.a.", "it division"}


def letters(k):
    return sum(c.isalpha() for c in k)


def person_like(k):
    return "\\" in k or "/" in k or "@" in k or k in KEEP or k in NAMES4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-repos", type=int, default=5)
    a = ap.parse_args()
    keys = json.load(open(C.PRIVATE / "mapping.json", encoding="utf-8"))["keys"]
    spread = {}
    sp = C.PRIVATE / "key_spread.tsv"
    if sp.exists():
        for line in open(sp, encoding="utf-8"):
            k, n, *_ = line.rstrip("\n").split("\t")
            spread[k] = int(n)
    why = {}
    for k in keys:
        if letters(k) <= 2:
            why[k] = "initials"
        elif len(k) == 3:
            why[k] = "3-char"
        elif len(k) == 4 and k not in NAMES4:
            why[k] = "4-char"
        elif k in MANUAL:
            why[k] = "manual"
        elif BOILER.search(k):
            why[k] = "boilerplate"
        elif spread.get(k, 0) >= a.max_repos and not person_like(k):
            why[k] = f"spread {spread[k]}"
    rv = C.PRIVATE / "review.tsv"
    if rv.exists():
        for line in open(rv, encoding="utf-8", errors="replace"):
            f = line.rstrip("\n").split("\t")
            if len(f) > 4 and f[0] == "label_person" and f[4] not in ("", "0"):
                v = f[1].strip()
                if not LABEL_NAME.fullmatch(v):
                    why[v.lower()] = "label"
    old = C.PRIVATE / "exclude.txt"
    keep_lines = []
    if old.exists():
        auto = False
        for l in open(old, encoding="utf-8"):
            if l.startswith("# auto"):
                auto = True
            elif l.strip() and auto:
                why.setdefault(l.strip(), "previous")
            elif l.strip():
                keep_lines.append(l.rstrip("\n"))
    with open(old, "w", encoding="utf-8") as f:
        for l in keep_lines:
            f.write(l + "\n")
        f.write("# auto (scripts/prune_keys.py)\n")
        for k in sorted(why):
            f.write(k + "\n")
    by = {}
    for r in why.values():
        r = r.split()[0]
        by[r] = by.get(r, 0) + 1
    print(f"excluded {len(why)} of {len(keys)} keys: {by}")


if __name__ == "__main__":
    main()
