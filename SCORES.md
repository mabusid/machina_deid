# Scores

Scorer `machina-deid-1`. Baseline (input copied unchanged) = 292. 20 attempts max, 2/hour.

| # | Submitted (ET) | Location | Commit | Score | Notes |
|---|---|---|---|---|---|
| 1 | 2026-11-22 ~06:00 | gs://builders-machina-submissions-use1/teams/b3240ed6-c290-471c-9476-499100a0db6c/attempt-1/ | 633d6af | **274** | Categories: leakage 1/20, consistency 1/15, distinct 2/10, relationships 11/20, eng. info 10/15, OLE hidden 2/10, packaging 5/10, **PDF scoped removal 0/300, PDF cross-consistency 0/200, non-collision 0/100**, drawing/model 188/200, OLE saved-account 2/25, OLE cross-stream 2/25, OLE preview 25/25, OLE integrity 25/25. Diagnosis: PDF page text never edited; short/generic OLE saved accounts not mapped. Batch run, 14 slices. Mapping 13,982 keys / 469 owners after prune_keys (spread probe + rules); STEP in-string only. Files: 44,690 changed, 143,845 unchanged, 187 fallback (copied unchanged; mostly encrypted zips). Upload verified: 188,722/188,722 corpus objects, README + code present. |
| 2 | 2026-11-22 ~06:45 | …/attempt-2/ | (see attempt-2/code) | pending | Same mapping (keys/owners byte-identical). Re-processed only PDF (page-text redaction with pseudonyms, probe: 251→1 leaks on 60 PDFs) and OLE files (property-set saved accounts/authors incl. short/generic: ole_prop 37, ole_all 12). 21,214 files re-made; other 167,508 copied server-side from attempt-1. |
