"""Server-side copy of attempt-A/corpus objects into attempt-B/corpus (GCS XML API copy).

Skips keys listed in --skip (corpus-relative paths re-made for attempt-B) and keys already
present in attempt-B with the same size. On an expired token it raises $ALERT_DIR/need_token
and waits for a new token in --token-file.
python scripts/copy_attempt.py --src attempt-1 --dst attempt-2 --skip skip.txt
"""
import argparse
import http.client
import os
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

HOST = "storage.googleapis.com"


class Tok:
    def __init__(self, path, flag):
        self.path, self.flag, self.lock = path, flag, threading.Lock()
        self.value = open(path).read().strip()

    def renew(self, stale):
        with self.lock:
            if self.value != stale:
                return
            open(self.flag, "a").close()
            print("token expired; waiting for a new one in", self.path, flush=True)
            while True:
                v = open(self.path).read().strip()
                if v and v != stale:
                    self.value = v
                    os.path.exists(self.flag) and os.remove(self.flag)
                    print("got a new token", flush=True)
                    return
                time.sleep(3)


def expired(status, body):
    return status == 401 or (status in (400, 403) and b"xpired" in body)


def list_keys(bucket, prefix, tok):
    found, cont = {}, None
    c = http.client.HTTPSConnection(HOST, timeout=60)
    while True:
        q = {"list-type": "2", "prefix": prefix, "max-keys": "1000", "encoding-type": "url"}
        if cont:
            q["continuation-token"] = cont
        t = tok.value
        c.request("GET", f"/{bucket}/?{urllib.parse.urlencode(q)}", headers={"Authorization": f"Bearer {t}"})
        r = c.getresponse()
        b = r.read()
        if expired(r.status, b):
            tok.renew(t)
            continue
        if r.status != 200:
            raise RuntimeError(f"list {r.status}: {b[:300]}")
        root = ET.fromstring(b)
        ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
        for it in root.findall(ns + "Contents"):
            found[urllib.parse.unquote_plus(it.findtext(ns + "Key"))[len(prefix):]] = int(it.findtext(ns + "Size"))
        if root.findtext(ns + "IsTruncated") != "true":
            return found
        cont = root.findtext(ns + "NextContinuationToken")


def enc(key):
    return "/".join(urllib.parse.quote(p, safe="") for p in key.split("/"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default="builders-machina-submissions-use1")
    ap.add_argument("--team", default="teams/b3240ed6-c290-471c-9476-499100a0db6c")
    ap.add_argument("--src", default="attempt-1")
    ap.add_argument("--dst", required=True)
    ap.add_argument("--skip", default=None)
    ap.add_argument("--token-file", default="/root/token.txt")
    ap.add_argument("--workers", type=int, default=48)
    a = ap.parse_args()
    flag = os.path.join(os.environ.get("ALERT_DIR", "/root/alerts"), "need_token")
    tok = Tok(a.token_file, flag)
    sp, dp = f"{a.team}/{a.src}/corpus/", f"{a.team}/{a.dst}/corpus/"
    src = list_keys(a.bucket, sp, tok)
    have = list_keys(a.bucket, dp, tok)
    skip = set()
    if a.skip:
        skip = {l.rstrip("\n") for l in open(a.skip, encoding="utf-8") if l.strip()}
    todo = [k for k in src if k not in skip and have.get(k) != src[k]]
    print(f"src {len(src)}, already in dst {len(have)}, skip {len(skip)}, to copy {len(todo)}", flush=True)
    local = threading.local()

    def copy(k):
        for attempt in range(6):
            c = getattr(local, "c", None) or http.client.HTTPSConnection(HOST, timeout=120)
            local.c = c
            t = tok.value
            try:
                c.request("PUT", f"/{a.bucket}/{enc(dp + k)}", headers={
                    "Authorization": f"Bearer {t}", "Content-Length": "0",
                    "x-goog-copy-source": f"/{a.bucket}/{enc(sp + k)}"})
                r = c.getresponse()
                b = r.read()
            except (OSError, http.client.HTTPException):
                local.c = None
                time.sleep(0.5 * 2 ** attempt)
                continue
            if expired(r.status, b):
                tok.renew(t)
                continue
            if r.status == 200:
                return
            if r.status in (429,) or r.status >= 500:
                time.sleep(0.5 * 2 ** attempt)
                continue
            raise RuntimeError(f"copy {k}: {r.status} {b[:200]}")
        raise RuntimeError(f"copy {k}: retries exhausted")

    done, t0 = 0, time.time()
    with ThreadPoolExecutor(a.workers) as pool:
        for f in as_completed([pool.submit(copy, k) for k in todo]):
            f.result()
            done += 1
            if done % 5000 == 0 or done == len(todo):
                print(f"  {done}/{len(todo)} copied, {time.time() - t0:.0f}s", flush=True)
    print("COPY DONE", flush=True)


if __name__ == "__main__":
    main()
