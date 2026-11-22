"""attempt2-skip.txt: corpus paths (attempt-1 names) of the files re-made for attempt 2."""
import json

sel = set(open("/root/private/attempt2-rels.txt", encoding="utf-8").read().split("\n"))
last = {}
for line in open("/root/private/state/attempt-1/status.jsonl", encoding="utf-8"):
    d = json.loads(line)
    last[d["rel"]] = d
skip = [last[r]["dst"].split("/attempt-1/corpus/", 1)[1] for r in sel]
open("/root/private/attempt2-skip.txt", "w", encoding="utf-8").write("\n".join(skip))
print(len(skip), "skip paths")
