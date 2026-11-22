"""Machina CAD de-identification pipeline.

Stages:
  harvest  -> collect identity candidates from paths, headers and metadata
  resolve  -> build a frozen, length-preserving mapping (private, never uploaded)
  transform-> rewrite every file with the frozen mapping, validate, fall back to original
  verify   -> leak scan + integrity summary, README.txt generation
"""
