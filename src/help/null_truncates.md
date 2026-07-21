# Null truncates & BB columns

## Truncates

In a DEL, compounds are built cycle by cycle. A **truncate** has some positions filled with real building blocks (BBs) and unused positions marked with a **null token** (e.g. `AgxNull`).

## BB order

**BB1** = first coupled position (C-terminus). Later BBs follow coupling order (N-terminus last).

Values come from **Configure Spreadsheet → 5 — DEL / Pedigree** column maps — **not** from splitting the compound ID (dash-containing BB names would break).

Optional **BB index CSV** supplies display indices for split-tree labels and export columns.

## Why configure this

Pedigree, lineage, RT assignment, and the analysis bundle all walk BB columns from all-null root → classes → full product.

Setup checklist: **DEL library setup**.
