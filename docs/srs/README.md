# SRS

| File | What it is |
|---|---|
| `Tally_SRS_v7_3_Complete.pdf` | The source of truth (SRS v7.3 Complete Edition, 34 pages). |
| `SRS_v7_3.raw.txt` | Reference extraction: the exact `pdftotext -layout` output of the PDF. |
| `SRS_v7_3.md` | Searchable copy, generated from the reference extraction. **Grep this one**, e.g. `grep -n "SYNC-3" docs/srs/SRS_v7_3.md`. |

Regenerate both with `uv run python -m tally_tools.srs` (needs poppler).

The reference extraction was produced with **pdftotext version 26.09.0** (poppler). It is
committed because poppler versions differ in whitespace and diagram layout, so re-running
`pdftotext` on another machine does not reproduce byte-identical output. Pinning it keeps the
faithfulness tests deterministic everywhere; `tools/tests/test_srs_transcription.py` ties it back
to the PDF by requirement-ID coverage. If you regenerate with a different poppler version, update
the version above and review the diff before committing.
