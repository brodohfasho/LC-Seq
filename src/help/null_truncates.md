# Null truncates and building-block columns

## DEL libraries and truncates

In a DNA-encoded library (DEL), each compound is built step by step. A **truncate** is a partially built molecule: some positions are filled with real building blocks (BBs) and unused positions are filled with a **null token** (often `AgxNull`).

## BB1, BB2, BB3…

In your spreadsheet, **BB1** is the first coupled position (C-terminus in peptide/DEL convention). **BB3** in a 3-cycle library is the last coupled position (N-terminus).

The analysis engine reads BB values from **mapped columns**, not by splitting the compound name. This avoids errors when a BB name contains dashes (e.g. `DLeu-DLeu-Pro`).

## Null token

The **null token** marks an empty position. Only non-null BBs define the equivalence class at each tier.

## Why this matters

Lineage and pedigree analysis use BB columns to walk from the all-null root → intermediate classes → full product. Configure BB columns on **Configure Spreadsheet → DEL / Pedigree** before running analysis.
