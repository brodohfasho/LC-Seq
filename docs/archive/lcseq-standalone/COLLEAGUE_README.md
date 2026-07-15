# LC-Seq

Pedigree-tree pruning for DNA-encoded library (DEL) cyclic-peptide LC-MS data.

A Rust core (peak detection, baseline modeling, multi-replicate score test) with
a Python frontend (data ingestion, plotting, CLI) wired together via PyO3 / maturin.

## What it does

Given replicated LC chromatograms for every member of a combinatorial cyclic-peptide
library, LC-Seq:

1. Fits a per-replicate Negative-Binomial baseline (sigma-clipped) and detects peaks
   against the chromatogram's local noise floor.
2. Runs a joint multi-replicate **score test** (Rao test on the NB likelihood) to
   estimate a shared peak position across replicates of the same equivalence class.
3. Combines per-replicate picks (earliest, most-significant, democratic-consensus)
   via a small Bayesian posterior whose prior is the score-test's z(k) landscape and
   whose evidence comes from the three pick streams treated as independent observations.
4. Walks the cassette pedigree tree — each node's chosen retention time gates which
   children are admissible (RPLC monotonicity in residue composition) — pruning
   subtrees whose parent peak failed.

## Layout

```
src/                 Rust crate (lcseq)
  evaluate/          consensus, score test, peak model, baselines
  peaks/             detection + baseline fitting
  bindings.rs        PyO3 surface
python/lcseq/        Python package
  cli.py             `lcseq` entry point
  io.py              xlsx ingestion
  render.py          summary figures
  debug.py           per-class inspection figures
tests/               Rust integration tests (incl. real_data fixture)
python/tests/        pytest suite
```

## Setup

```sh
# Python env
uv sync

# Build & install the Rust extension into the active env
maturin develop --release
```

## Tests

```sh
cargo test                                  # Rust (unit + integration)
.venv/bin/pytest                            # Python (fast)
.venv/bin/pytest -m slow                    # Python (parses the full master xlsx)
```

The slow pytest marker requires the full master xlsx, which is **not** committed
(see "Data" below).

## Data

`data/LDEL_ssPID_10-40_Master3.0.xlsx` (the master input) is gitignored. Drop your
own xlsx into `data/` to run end-to-end. Time units in the xlsx are seconds; the
ingestion layer leaves them in seconds and the user-facing CLI/figures convert to
minutes at the boundary.

A small fixture (`tests/fixtures/real_sample.json`) ships with the repo so the
Rust integration tests run without the master file.

## License

MIT — see [LICENSE](LICENSE).
