# src/core/csv_io.py
"""
Shared CSV encoding for scientist-facing exports.

Windows Excel often opens plain UTF-8 CSVs as the system ANSI code page, which
mojibakes characters such as β (U+03B2 → ``Î²``). Writing UTF-8 **with BOM**
(``utf-8-sig``) makes Excel detect UTF-8 without requiring users to change
import settings. Python, pandas, and R strip the BOM when reading with
``utf-8-sig`` / equivalent.
"""

from __future__ import annotations

# Use for all user-facing CSV *writes*. Prefer the same encoding when reading
# those files back in tests or reload paths.
CSV_EXPORT_ENCODING = "utf-8-sig"
