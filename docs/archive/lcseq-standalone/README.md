# docs/archive/lcseq-standalone

Colleague's **standalone** LC-Seq tooling from before integration into the main app.
Not used by the CustomTkinter GUI.

| File | Purpose |
|------|---------|
| `lcseq_io.py` | Parse fixed-schema LDEL master xlsx → `bbs_per_position` + chromatogram dict |
| `cli.py` | Command-line: `parse_xlsx → evaluate_library → render_pruned_tree` |
| `debug.py` | Matplotlib per-class / lineage diagnostic figures |
| `COLLEAGUE_README.md` | Original project README (uv workflow, data layout) |
| `uv.lock` | Colleague's uv lockfile (historical) |
| `tests/` | pytest for xlsx I/O and CLI (slow tests need master xlsx under `LC-Seq-New-master/data/`) |

## Running the archived CLI (optional)

Requires a built `lcseq` extension (`maturin develop` in `LC-Seq-New-master/`) and Graphviz
on PATH for tree output:

```powershell
cd docs/archive/lcseq-standalone
..\..\..\venv\Scripts\python.exe cli.py run path\to\master.xlsx --bbs Val Phe Leu --out tree --unit minutes --tolerance 0.5
```

## Why archived

The main LC-Seq app loads spreadsheets via Configure Spreadsheet, stores compounds in SQLite,
and adapts data through `src/core/pedigree_adapter.py`. Keeping duplicate xlsx ingestion and
a separate CLI in the active package caused confusion without adding runtime value.
