# scripts/pyi_rth_mpl_tkagg.py
"""PyInstaller runtime hook: use TkAgg (required for CustomTkinter + FigureCanvasTkAgg)."""

import os

os.environ.setdefault("MPLBACKEND", "TkAgg")
