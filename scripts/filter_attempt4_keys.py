"""Keep attempt-3 keys, plus new email addresses and person phrases with a real given name.

Bare tokens from this pass (heatsink, klemmblech, spacer, ...) match filenames and engineering
text, so they are dropped. Writes mapping.json in place. Refuses to change an old key.
"""
import json
import re

from deid.matcher import Replacer
from deid.paths import rename_rel

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
wilma yvonne zachary zoe
hans klaus peter wolfgang juergen jurgen dieter helmut werner horst manfred heinz franz
josef otto ernst friedrich wilhelm heinrich ludwig bernhard andreas markus matthias
torsten uwe ralf rainer bernd holger olaf sven nils ole kai florian tobias dirk jens
alain christophe laurent thierry pascal yves antoine francois guillaume michel
fabian azocar vecchio aston timmers westbury mooney guillod hochecker spruyt amann
alejandro
""".split())


def keep_new(k: str) -> bool:
    if "@" in k:
        return True
    if re.fullmatch(r"[a-z]\. ?[a-z]{4,}", k):
        return True
    parts = [p for p in re.split(r"[^a-z]+", k) if p]
    return len(parts) >= 2 and (parts[0] in GIVEN or parts[-1] in GIVEN)


def main():
    old = json.load(open("/root/private/mapping.attempt3.json"))
    cur = json.load(open("/root/private/mapping.json"))
    ak = old["keys"]
    added = {k: v for k, v in cur["keys"].items() if k not in ak and keep_new(k)}
    for k, v in ak.items():
        if cur["keys"].get(k, v) != v:
            raise SystemExit(f"old key changed: {k}")
    cur["keys"] = {**ak, **added}
    json.dump(cur, open("/root/private/mapping.json", "w"), indent=0, sort_keys=True)
    from deid import config as C
    Ro, Rn = Replacer.load("/root/private/mapping.attempt3.json"), Replacer.load("/root/private/mapping.json")
    rels = [r for r in open("/root/private/attempt3-rels.txt", encoding="utf-8").read().splitlines() if r]
    changed = [r for r in rels if rename_rel(r, Ro) != rename_rel(r, Rn)]
    print(f"kept {len(added)} new keys; mapping {len(cur['keys'])}; pdf paths changed {len(changed)}")
    shown = [k for k in sorted(added) if " " in k or "," in k][:30]
    print("sample", shown)


if __name__ == "__main__":
    main()
