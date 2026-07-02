# scripts/assess_peak_picker_compound.py
"""One-off assessment script for peak picking on a single compound."""

from __future__ import annotations

import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.config_manager import ConfigManager
from src.core.data_processor import DataProcessor
from src.core.data_store import DataStore
from src.core.lcseq_backend import get_peak_picker_backend
from src.core.peak_picker_python import (
    _compute_prominence,
    _local_maxima,
    estimate_baseline,
    estimate_rolling_baseline,
    nearest_index,
    p_at_least,
    valley_bounds,
)


def main() -> None:
  cid = "DAlaMe-DPhe-LA03\x1fDEL-0045"
  cfg = ConfigManager().load_default_config()
  db = ROOT / "output" / "databases" / "LDEL_10-40_AllData_index_20260701.db"
  store = DataStore(db_path=db, use_memory=False)
  base = store.get_compound(cid)
  proc = DataProcessor()
  raw = store.get_raw_chromatogram(cid)
  series = pd.Series(
      {
          cfg.compound_id_column: base.primary_compound_id,
          cfg.chromatographic_data_column: raw,
          cfg.compound_variant_column: base.variant_label,
      }
  )
  comp, _ = proc.parse_dataframe_row_to_compound(series, cfg, 0)
  pts = sorted(comp.data_points, key=lambda dp: dp.time)
  times = [float(dp.time) for dp in pts]
  inten = [float(dp.get_count("Deduplicated Count") or 0.0) for dp in pts]
  alpha = 0.001
  backend = get_peak_picker_backend()
  print("backend:", backend.info())
  peaks = backend.find_peaks(times, inten, alpha)
  total_area = sum(p.area for p in peaks)
  g = estimate_baseline(inten)
  print(f"n_points={len(times)} dt={times[1]-times[0]:.0f}s global_mu={g.mu:.2f} global_sigma={g.sigma:.2f}")
  print()
  header = (
      "peak rt I area pct prom p roll_mu sigma r width p_h p_a driver valley"
  )
  print(header)
  for p in peaks:
      idx = nearest_index(times, p.rt)
      left, right = valley_bounds(inten, idx)
      b = estimate_rolling_baseline(inten, idx, left, right)
      width = right - left + 1
      vals = [inten[i] for i in range(left, right + 1)]
      ph = p_at_least(p.intensity, b.mu, b.dispersion_r)
      scaled_r = b.dispersion_r * width if b.dispersion_r else None
      pa = p_at_least(p.area, b.mu * width, scaled_r)
      driver = "height" if ph <= pa else "area"
      pct = 100 * p.area / total_area if total_area else 0.0
      r_str = f"{b.dispersion_r:.2f}" if b.dispersion_r else "pois"
      print(
          f"{p.peak_index:4d} {p.rt:4.0f} {p.intensity:3.0f} {p.area:4.0f} "
          f"{pct:5.2f} {p.prominence:4.1f} {p.p_value:.2e} {b.mu:6.2f} "
          f"{b.sigma:5.2f} {r_str:>5} {width:5d} {ph:.2e} {pa:.2e} {driver:6s} {vals}"
      )

  print("\n--- All local maxima (before significance filter) ---")
  for idx in _local_maxima(inten):
      h = inten[idx]
      left, right = valley_bounds(inten, idx)
      b = estimate_rolling_baseline(inten, idx, left, right)
      width = right - left + 1
      area = sum(inten[left : right + 1])
      prom = _compute_prominence(inten, idx)
      ph = p_at_least(h, b.mu, b.dispersion_r)
      scaled_r = b.dispersion_r * width if b.dispersion_r else None
      pa = p_at_least(area, b.mu * width, scaled_r)
      pval = min(ph, pa)
      kept = pval < alpha / 2
      print(
          f"rt={times[idx]:.0f} h={h:.0f} prom={prom:.1f} roll_mu={b.mu:.2f} "
          f"p={pval:.2e} kept={kept} valley={[inten[i] for i in range(left, right+1)]}"
      )
  print("\n--- Policy simulations (alpha=0.001, threshold=0.0005) ---")
  thresh = alpha / 2.0
  rows = []
  for idx in _local_maxima(inten):
      left, right = valley_bounds(inten, idx)
      b = estimate_rolling_baseline(inten, idx, left, right)
      width = right - left + 1
      h = inten[idx]
      area = sum(inten[left : right + 1])
      prom = _compute_prominence(inten, idx)
      ph = p_at_least(h, b.mu, b.dispersion_r)
      scaled_r = b.dispersion_r * width if b.dispersion_r else None
      pa = p_at_least(area, b.mu * width, scaled_r)
      rows.append(
          {
              "rt": times[idx],
              "h": h,
              "prom": prom,
              "mu": b.mu,
              "sigma": b.sigma,
              "ph": ph,
              "pa": pa,
              "p": min(ph, pa),
          }
      )

  def show(name: str, pred) -> None:
      kept = [r for r in rows if pred(r)]
      rts = [int(r["rt"]) for r in kept]
      print(f"{name}: {len(kept)} peaks -> {rts}")

  show("A current both p_h AND p_a", lambda r: r["ph"] < thresh and r["pa"] < thresh)
  show("B both p_h AND p_a", lambda r: r["ph"] < thresh and r["pa"] < thresh)
  show("C current + prom>=5", lambda r: r["p"] < thresh and r["prom"] >= 5)
  show("D current + prom>=10", lambda r: r["p"] < thresh and r["prom"] >= 10)
  show("E height test only", lambda r: r["ph"] < thresh)
  show("F height + prom>=5", lambda r: r["ph"] < thresh and r["prom"] >= 5)
  show("G prom>=10 only", lambda r: r["prom"] >= 10)

  focus = next(r for r in rows if r["rt"] == 1155.0)
  print(f"\nRT 1155: {focus}")
  store.close()


if __name__ == "__main__":
  main()
