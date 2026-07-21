# Configuration files

LC-Seq stores settings under the project `config/` directory. The **Configure Spreadsheet** UI is the normal way to create and edit these files; edit JSON by hand only for backup, sharing, or debugging.

## File locations

| File | Written by | Purpose |
|------|------------|---------|
| `config/settings.json` | App on exit / when settings change | Window size, last paths, logging, optional embedded default spreadsheet config |
| `config/default_config.json` | **Save as default** in Configure | Spreadsheet parsing config loaded when no named config is chosen |
| `config/configs/<name>.json` | **Save named config** in Configure | Reusable presets per dataset format (local only; gitignored) |

SQLite databases are **not** in `config/`; they live under `output/databases/`.

---

## `settings.json` (application settings)

Flat JSON object matching `AppSettings`:

| Key | Type | Description |
|-----|------|-------------|
| `last_loaded_file` | string or null | Absolute path to last spreadsheet |
| `last_loaded_sheet` | string or null | Excel sheet name (null for CSV) |
| `last_active_database_path` | string or null | Last active `.db` file (full or index) |
| `window_width` | integer | Main window width (≥ 400) |
| `window_height` | integer | Main window height (≥ 300) |
| `log_level` | string | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |
| `log_file` | string | Log file path (default `logs/lc_seq.log`) |
| `default_spreadsheet_config` | object or omitted | Embedded `SpreadsheetConfig` (same schema as below) |

If the file is missing or invalid JSON, defaults are used and the app still starts.

---

## Spreadsheet configuration

Used in `default_config.json`, inside `settings.json` → `default_spreadsheet_config`, and inside named configs (see below).

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `compound_id_column` | string | yes | Spreadsheet column for compound / library ID |
| `chromatographic_data_column` | string | yes | Column containing delimiter-encoded chromatogram text |
| `compound_variant_column` | string or null | no | Column distinguishing variants of the same primary ID |
| `delimiters` | string array | yes | Ordered list (e.g. `[";", ":", ","]`) — order defines parse steps |
| `time_column_index` | integer | yes | 0-based index of time within each parsed data point |
| `count_column_indices` | integer array | yes | 0-based indices of count fields (same length as `count_names`) |
| `count_names` | string array | yes | Display names for each count channel (unique) |
| `selected_metadata_columns` | string array | no | Extra spreadsheet columns indexed for search |
| `null_token` | string | no* | Token for unfilled BB positions (default `AgxNull`). Required for pedigree / split-tree. |
| `library_cycle_count` | integer | no* | Coupling cycles: `2`, `3`, or `4` (default `3`) |
| `bb_position_columns` | string array (length 4) | no* | Spreadsheet columns for BB1…BB4 in C→N order; unused slots are `""` |
| `bb_index_map` | object | no | Optional building-block name → display index (from BB index CSV) |
| `bb_index_csv_path` | string or null | no | Path of the last loaded BB index file (informational) |
| `analysis_time_unit` | string | no | Default analysis UI time unit: `seconds` or `minutes` |

\* DEL / pedigree fields are optional for basic chromatogram viewing; they must be set (via Configure Spreadsheet → **5 — DEL / Pedigree**) before Library Analysis pedigree or split-tree workflows.

A config is **complete** for database builds when all required chromatogram fields are set and indices/names are consistent (see `SpreadsheetConfig.is_complete()`). Use `pedigree_configured()` in code to check BB columns + cycle count.

### Example (`default_config.json`)

```json
{
  "compound_id_column": "Compound_ID",
  "chromatographic_data_column": "chromatogram_data",
  "compound_variant_column": null,
  "delimiters": [";", ":", ","],
  "time_column_index": 0,
  "count_column_indices": [1, 2],
  "count_names": ["Count", "Deduplicated Count"],
  "selected_metadata_columns": ["Batch", "Library"],
  "null_token": "AgxNull",
  "library_cycle_count": 3,
  "bb_position_columns": ["BB1", "BB2", "BB3", ""],
  "bb_index_map": {},
  "bb_index_csv_path": null,
  "analysis_time_unit": "seconds"
}
```

### DEL / BB index notes

- Map BB columns in Configure Spreadsheet tab **5 — DEL / Pedigree**; optional UTF-8 or Excel BB index CSV for display indices on split-tree labels and exports.
- Named presets under `config/configs/` can store the full schema including `bb_index_map` (local only; gitignored).
- See in-app help **Null truncates & BB columns** and [APPLICATION_WORKFLOW.md](APPLICATION_WORKFLOW.md).

---

## Named configs (`config/configs/*.json`)

Saved presets live under `config/configs/` on your machine only (gitignored). See `config/examples/named_config.example.json` for the on-disk schema.

Wrapper written by **Save named config**:

| Key | Type | Description |
|-----|------|-------------|
| `version` | string | Config format version (currently `1.0`) |
| `name` | string | Display name shown in the UI |
| `config` | object | Spreadsheet configuration (schema above) |

Example:

```json
{
  "version": "1.0",
  "name": "MyLibrary",
  "config": {
    "compound_id_column": "ID",
    "chromatographic_data_column": "data",
    "delimiters": [";", ","],
    "time_column_index": 0,
    "count_column_indices": [1],
    "count_names": ["Count"],
    "selected_metadata_columns": []
  }
}
```

Older files without a `config` wrapper are still accepted (body treated as the spreadsheet config).

---

## Notes

- Column names must match the loaded spreadsheet exactly.
- `time_column_index` and `count_column_indices` refer to positions **after** delimiter parsing in the chromatogram string, not spreadsheet columns.
- Do not commit private `settings.json` or `config/configs/` presets (they are gitignored by default).
