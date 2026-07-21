# DEL library setup

Checklist for DNA-encoded libraries before **Library Analysis**, pedigree, lineage, or split-tree work.

## Where

**Configure Spreadsheet → tab 5 — DEL / Pedigree**, then **Accept configuration**.

## Steps

1. **Library cycle count** — `2`, `3`, or `4` coupling cycles.
2. **BB columns** — map **BB1…BBn** to spreadsheet columns in **C→N** order (BB1 = first coupled / C-terminus).
3. **Null token** — placeholder for empty positions (e.g. `AgxNull`). Must match the sheet exactly.
4. **BB index CSV (optional)** — UTF-8 or Excel file of BB name → display index for tree labels / exports.
5. **Validate** — if you loaded an index, run validation (missing / encoding mismatches are reported here).
6. **Accept configuration** — required for the app to use the mapping. Optionally **Save named config** for reuse.

## Why this matters

Pedigree, lineage, RT assignment, and the analysis bundle read BB values from these columns — **not** by splitting compound IDs (which breaks names that contain dashes).

## After Accept

1. Build or load a database.
2. Open **Library Analysis** → scan → RT assignment.
3. For paper-like runs: **Old-school** picking + **Direct pick** mode (see **Peak picking**).

See also **Null truncates & BB columns**.
