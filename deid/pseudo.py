"""Deterministic, length- and case-preserving pseudonyms.

Every letter run ("token") maps to a fake word with the same number of letters.
Digits and separators are kept, so 'J. Smith', 'jsmith', 'SMITH' and
'jsmith@acme.com' all stay byte-length identical and mutually consistent.
"""
import hashlib
import hmac
import re

TOKEN_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+|[^A-Za-z\d]+")

FIRST = """
ada al amy ann ava bea ben cal cy dan dee eli eva fay gus hal ian ida ivy jon kai kim
lea leo liv lou max mia ned nia oli pat ray rex rio sal sam tad tia ty uma val vic wes
zoe abby alba alex anna aria bart beth cara cole dale dana dean drew eden emil enzo erin
ezra finn gail gina hank hugo ines iris ivan jade jake joel judd kara kurt lana lars lena
liam lila lisa luca luke lyle mara mike mila nell nico nina noah nora omar opal otis owen
paul remy rhea rory rosa ruth sage seth tara tess theo tobi vera wade will yara zane
aaron adele alice amara anton april arlo basil bella blair brian carla carlo cecil chloe
clara dante delia derek dylan edith elena elias ellis elsie emery ethan fiona flora frank
gemma grace hazel heidi helen henry irene isaac jamie jason jonas joyce julia karen kevin
laila laura leona lewis linda logan lucia lydia mabel maeve marco maria milan miles moira
nadia naomi nolan oscar paige pedro petra piper quinn ralph reese renee robin roman rufus
sadie sasha simon sofia stella tessa tilda tomas uriel vince wanda wendy xavier yusuf
adrian alexis amelia andrea arthur aubrey benson bianca brenda calvin carmen connor daniel
daphne declan dorian easton edward elaine eloise esther felix gideon hailey harlan ingrid
isabel jasper jolene kendra landon leslie lionel louisa magnus marcel marina martin miriam
morgan nathan oliver philip rachel regina rowena sabine samuel selena sienna sylvia thomas
trevor ursula vernon violet walter wesley winona yvonne zander
""".split()
LAST = """
ash bay cox day fox gay hay kay lee low may ng orr poe ray roe tan yu
abel ames bain bell best birk bond cole cook dale dean dunn eddy ford gale gray hale hart
holt hood hunt kemp kent lake lane lowe lund mack marsh mead moss nash neal noel park
pike pope rand reed rhee ross rowe rudd sand self shaw snow stone tate todd vale wade ward
webb west wolf york adler ayala baker banks barry bates blake boone brand brook burke
byrne carey chase clark cohen crane cross dixon doyle drake duffy ellis evans finch flynn
frost gates grant green hayes hicks irwin jones keane kelly knox lamb lloyd lucas lynch
mason meyer mills moore nolan olsen owens perry price quinn reyes riley rossi sharp
stark stone swift tapia tracy tyler upton vance walsh wells wyatt young zeller
abbott archer arnold atkins barker barton bishop bowman briggs brooks bryant burton
carson carter chavez conway dalton dawson duncan easton elliot farley fisher fowler
garner gibson graham hanson harper hobbes holden hughes jensen jordan keller kramer
lawson lennox lowell madden marlow mercer monroe morton murphy nelson norris oakley
palmer parker porter rankin reeves rhodes sawyer shelby sloane spence sutton thorne
tucker turner vaughn walker warren weaver whelan wilcox winter wright
""".split()
_CONS = "bcdfghjklmnprstvwz"
_VOW = "aeiou"


def tokens(s: str):
    return TOKEN_RE.findall(s)


def is_word(tok: str) -> bool:
    return tok.isalpha()


def _by_len(words):
    d = {}
    for w in words:
        d.setdefault(len(w), []).append(w)
    return d


_FIRST_BY_LEN = _by_len(FIRST)
_LAST_BY_LEN = _by_len(LAST)


class Pseudonymizer:
    """Single-threaded during resolve: guarantees distinct tokens get distinct pseudonyms."""

    def __init__(self, secret: bytes, reserved=()):
        self.secret = secret
        self.map: dict[str, str] = {}
        self.used: set[str] = set()
        self.reserved = set(reserved)

    def _stream(self, token: str, attempt: int):
        ctr = 0
        while True:
            h = hmac.new(self.secret, f"{token}|{attempt}|{ctr}".encode(), hashlib.sha256).digest()
            yield from h
            ctr += 1

    def _gen(self, token: str, n: int, style: str, attempt: int) -> str:
        rnd = self._stream(token, attempt)
        pool = (_FIRST_BY_LEN if style == "first" else _LAST_BY_LEN if style == "last" else {}).get(n)
        if pool and attempt < 4:
            return pool[next(rnd) % len(pool)]
        out = []
        vowel = next(rnd) % 3 == 0
        while len(out) < n:
            out.append(_VOW[next(rnd) % 5] if vowel else _CONS[next(rnd) % len(_CONS)])
            vowel = not vowel if next(rnd) % 5 else vowel
        return "".join(out)

    def token(self, tok: str, style: str = "name") -> str:
        """Pseudonym for one letter token (lowercase in, lowercase out)."""
        t = tok.lower()
        if t in self.map:
            return self.map[t]
        for attempt in range(200):
            p = self._gen(t, len(t), style, attempt)
            if len(t) <= 2 and p != t:
                break  # initials and fragments are never standalone keys; uniqueness impossible
            if p != t and p not in self.used and p not in self.reserved:
                break
        else:
            raise RuntimeError(f"pseudonym space exhausted for length {len(t)}")
        self.map[t] = p
        self.used.add(p)
        return p

    def phrase(self, s: str, replace_tok, style_for=lambda i, tok: "name") -> str:
        """Lowercase pseudonym for a phrase; tokens where replace_tok(tok) is False are kept."""
        out = []
        for i, tok in enumerate(tokens(s.lower())):
            if is_word(tok) and replace_tok(tok):
                out.append(self.token(tok, style_for(i, tok)))
            else:
                out.append(tok)
        res = "".join(out)
        assert len(res) == len(s), (s, res)
        return res


def apply_case(orig: bytes, pseudo: str) -> bytes:
    """Copy the per-character case of orig onto a lowercase pseudonym of equal length."""
    out = bytearray(pseudo.encode("ascii"))
    for i, c in enumerate(orig):
        if 65 <= c <= 90 and 97 <= out[i] <= 122:
            out[i] -= 32
    return bytes(out)
