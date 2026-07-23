# tests/test_library_scan_store.py
"""Tests for library scan pickle persistence, export, and validation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.core.library_metrics import LibraryScanData, ScannedEntry
from src.core.library_metrics_store import (
    delete_session_scan,
    delete_all_session_scans,
    export_scan_pickle,
    list_session_scan_paths,
    load_scan_pickle,
    load_session_scan,
    other_session_scan_paths,
    save_session_scan,
    session_scan_exists,
    session_scan_path,
    suggested_scan_export_filename,
    validate_scan_for_database,
)
from src.models.spreadsheet_config import SpreadsheetConfig


def _sample_scan(*, source_name: str = "lib.db") -> LibraryScanData:
    return LibraryScanData(
        entries=[
            ScannedEntry(
                compound_id="c1",
                times=[0.0, 1.0],
                counts_by_channel={"Count": [1.0, 2.0]},
            )
        ],
        entries_attempted=1,
        entries_used=1,
        entries_skipped=0,
        channel_names=["Count"],
        source_database_name=source_name,
        scanned_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
    )


def _config() -> SpreadsheetConfig:
    return SpreadsheetConfig(
        compound_id_column="id",
        chromatographic_data_column="data",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
    )


class TestLibraryScanStore:
    def test_save_load_and_delete_session_scan(self, tmp_path: Path) -> None:
        db_path = tmp_path / "MyLib_index_20260703.db"
        scan = _sample_scan()
        save_session_scan(scan, db_path)
        assert session_scan_exists(db_path)
        assert scan.source_database_name == db_path.name
        assert scan.scanned_at is not None

        loaded = load_session_scan(db_path)
        assert loaded is not None
        assert loaded.entries_used == 1
        assert loaded.channel_names == ["Count"]

        assert delete_session_scan(db_path) is True
        assert not session_scan_exists(db_path)
        assert delete_session_scan(db_path) is False

    def test_export_and_load_external_pickle(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        scan = _sample_scan(source_name=db_path.name)
        dest = tmp_path / "exports" / suggested_scan_export_filename(db_path, scan)
        export_scan_pickle(scan, dest)
        loaded = load_scan_pickle(dest)
        assert loaded.entries_used == scan.entries_used
        assert "library_scan" in dest.name

    def test_validate_scan_rejects_unknown_channels(self, tmp_path: Path) -> None:
        scan = _sample_scan()
        scan.channel_names = ["MissingChannel"]
        report = validate_scan_for_database(
            scan,
            database_path=tmp_path / "lib.db",
            config=_config(),
            compound_count=1,
        )
        assert not report.ok
        assert any("MissingChannel" in err for err in report.errors)

    def test_validate_scan_warns_on_database_mismatch(self, tmp_path: Path) -> None:
        scan = _sample_scan(source_name="other.db")
        report = validate_scan_for_database(
            scan,
            database_path=tmp_path / "active.db",
            config=_config(),
            compound_count=1,
        )
        assert report.ok
        assert report.warnings

    def test_load_scan_pickle_rejects_invalid_object(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.pkl"
        path.write_bytes(b"not a pickle")
        with pytest.raises(Exception):
            load_scan_pickle(path)

    def test_delete_all_session_scans(self, tmp_path: Path, monkeypatch) -> None:
        library_dir = tmp_path / "library_data"
        library_dir.mkdir()
        monkeypatch.setattr(
            "src.core.library_metrics_store.get_library_data_dir",
            lambda: library_dir,
        )
        db_a = tmp_path / "LibA_index_20260703.db"
        db_b = tmp_path / "LibB_index_20260704.db"
        # Bypass single-cache replacement so delete_all can exercise multiple files.
        path_a = session_scan_path(db_a)
        path_b = session_scan_path(db_b)
        export_scan_pickle(_sample_scan(source_name=db_a.name), path_a)
        export_scan_pickle(_sample_scan(source_name=db_b.name), path_b)
        assert len(list_session_scan_paths()) == 2
        assert delete_all_session_scans() == 2
        assert not list_session_scan_paths()
        assert delete_all_session_scans() == 0

    def test_save_session_scan_keeps_only_one_cache(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        library_dir = tmp_path / "library_data"
        library_dir.mkdir()
        monkeypatch.setattr(
            "src.core.library_metrics_store.get_library_data_dir",
            lambda: library_dir,
        )
        db_a = tmp_path / "LibA_index_20260703.db"
        db_b = tmp_path / "LibB_index_20260704.db"
        save_session_scan(_sample_scan(source_name=db_a.name), db_a)
        assert session_scan_exists(db_a)
        assert other_session_scan_paths(db_b) == [session_scan_path(db_a)]

        removed = save_session_scan(_sample_scan(source_name=db_b.name), db_b)
        assert removed == [session_scan_path(db_a)]
        assert session_scan_exists(db_b)
        assert not session_scan_exists(db_a)
        assert list_session_scan_paths() == [session_scan_path(db_b)]
        assert other_session_scan_paths(db_b) == []
