# LC-Seq-New-master (Rust analysis engine)

Rust core + Python bindings for pedigree null-truncation analysis. This folder is a **maturin subproject** consumed by the main LC-Seq application — not a standalone app.

## What stays here

| Path | Role |
|------|------|
| `src/` | Rust engine: peak picking, consensus, pedigree walk |
| `python/lcseq/__init__.py` | Re-exports native API + `render_pruned_tree` |
| `python/lcseq/render.py` | Graphviz pedigree figure renderer |
| `python/tests/` | Package tests (`test_bindings.py`, `test_render.py`) |
| `tests/` | Rust integration tests + `fixtures/real_sample.json` |
| `scripts/extract_real_fixture.py` | Regenerate fixture from master xlsx (dev) |

## Build (developers)

From the **repo root** venv — see [dev/DEVELOPER_SETUP.md](../dev/DEVELOPER_SETUP.md):

```powershell
cd LC-Seq-New-master
..\venv\Scripts\maturin.exe develop --release
```

Verify: `..\venv\Scripts\python.exe -c "import lcseq; print(lcseq.find_peaks)"`

## Archived standalone tooling

Earlier standalone LDEL xlsx loader, CLI, and matplotlib debug plots live in
[dev/archive/lcseq-standalone/](../dev/archive/lcseq-standalone/). The main app uses
SQLite + `src/core/pedigree_adapter.py` instead of `parse_xlsx`.

## Integration reference

See [dev/LC-Seq-New-master-ANALYSIS.md](../dev/LC-Seq-New-master-ANALYSIS.md) for the
full API surface, LC-Seq wrapper map, and what requires Rust vs Python fallback.

## License

MIT — see [LICENSE](LICENSE).
