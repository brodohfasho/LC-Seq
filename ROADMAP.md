# LC-Seq Development Roadmap

This roadmap outlines the development phases for the LC-Seq chromatographic data analysis application. Phases 1–12 are feature development (complete). **Phases 13–14** are the release path (documentation and deployment). **Phase 15** is optional post-launch testing and hardening—do after the paper release when time permits.

## Project Overview

**Application Type**: Desktop application (Python-based, cross-platform capable, starting with Windows focus)  
**Core Functionality**: Load, configure, and visualize chromatographic data from spreadsheets  
**Target Users**: Scientists and researchers analyzing chromatographic time-series data (including DNA encoded library data)

**Workflow**:
1. Load spreadsheet (.csv containing possibly millions-billions of rows)
2. Configure spreadsheet (select columns, delimiters, time/count fields, metadata columns)
3. **Primary:** Open Chromatogram Visualizer and **parse/plot on demand** per compound from the loaded sheet
4. **Optional:** Create or load a **bulk SQLite** database under `output/databases/` for repeated indexed access or future full-sheet search (Phase 11)
5. Query database (visual query builder — Phase 11, when bulk DB is in use)
6. Visualize data (count vs time; optional overlay features in future phases)

---

## Phase 1: Project Foundation & Setup

### 1.1 Project Structure
- [x] Create project directory structure following best practices
- [x] Set up Python virtual environment
- [x] Create requirements.txt with initial dependencies
- [x] Set up .gitignore for Python projects
- [x] Create README.md with project description and setup instructions
- [x] Initialize basic project documentation structure

### 1.2 Development Environment
- [x] Configure development tools (linter, formatter)
- [x] Set up testing framework (pytest)
- [x] Create basic test directory structure
- [x] Set up logging configuration
- [x] Create configuration file structure for app settings

### 1.3 Core Dependencies
- [x] Research and select GUI framework (customtkinter)
- [x] Select spreadsheet reading library (pandas, openpyxl, xlrd)
- [x] Select plotting library (matplotlib)
- [x] Document dependency choices and rationale
- [x] Install and verify all dependencies

---

## Phase 2: Data Models & Core Logic

### 2.1 Data Models
- [x] Design Compound data model (ID, metadata columns, chromatographic data)
- [x] Design ChromatographicDataPoint model (time, count values)
- [x] Design SpreadsheetConfig model (delimiters, column mappings, parsing rules)
- [x] Design AppSettings model (default configs, last loaded file, user preferences)
- [x] Implement data validation logic for all models

### 2.2 Configuration Management
- [x] Design configuration file format (JSON)
- [x] Implement configuration loader/saver
- [x] Create default configuration template
- [x] Implement configuration validation
- [x] Add error handling for corrupted/invalid configs

### 2.3 Data Parsing Logic
- [x] Implement delimiter parsing engine (handles multiple delimiters in sequence)
- [x] Create parser for chromatographic data strings
- [x] Implement parsing preview/test functionality
- [x] Add error handling for malformed data
- [x] Create unit tests for parsing logic

---

## Phase 3: Main Screen UI

### 3.1 Main Window Layout
- [x] Design main window structure
- [x] Implement window title and basic styling
- [x] Create primary "Enter Chromatogram Visualizer" button
- [x] Create "Load Spreadsheet" button
- [x] Create "Configure Spreadsheet" button
- [x] Implement button state management (disable visualizer until ready)

### 3.2 State Management
- [x] Implement application state tracking (spreadsheet loaded, configured)
- [x] Create state change handlers
- [x] Implement button enable/disable logic based on state
- [x] Add visual feedback for button states
- [x] Display status messages for user guidance

### 3.3 Navigation Framework
- [x] Design navigation system between screens
- [x] Implement screen switching logic
- [x] Create base window class for consistency
- [x] Add window close handlers and cleanup

---

## Phase 4: Spreadsheet Loading

### 4.1 File Selection
- [x] Implement file dialog for spreadsheet selection
- [x] Support Excel (.xlsx, .xls) and CSV file formats
- [x] Add file format validation
- [x] Display selected file path to user
- [x] Store last loaded file path in settings

### 4.2 Data Loading
- [x] Implement spreadsheet reading (pandas)
- [x] Handle different Excel sheet selection (if multiple sheets)
- [x] Load data into memory with error handling
- [x] Validate basic file structure (has rows, has columns)
- [x] Display loading progress/status

### 4.3 Data Validation
- [x] Check for required columns (Compound ID, Chromatographic Data)
- [x] Validate data types where possible
- [x] Display validation errors to user
- [x] Allow user to retry or select different file

---

## Phase 5: Spreadsheet Configuration - Part 1 (Column Selection)

### 5.1 Configuration Screen Layout
- [x] Create configuration window/dialog
- [x] Display loaded spreadsheet column headers
- [x] Create UI for selecting Compound ID column
- [x] Create UI for selecting Chromatographic Data column
- [x] Add validation for column selections

### 5.2 Column Selection Logic
- [x] Implement column selection handlers
- [x] Validate that selected columns exist
- [x] Store column selections in configuration
- [x] Display selected columns to user
- [x] Allow user to change selections

---

## Phase 6: Spreadsheet Configuration - Part 2 (Delimiter Configuration)

### 6.1 Delimiter Selection UI
- [x] Create delimiter configuration interface
- [x] Allow user to specify delimiter sequence (order matters)
- [x] Support common delimiters (comma, semicolon, colon, tab, etc.)
- [x] Allow custom delimiter input
- [x] Display delimiter sequence visually

### 6.2 Parsing Preview
- [x] Implement test data input field (sample from spreadsheet)
- [x] Create "Test Parse" button
- [x] Display parsed results in preview table/grid
- [x] Show parsing errors if any
- [x] Allow user to adjust delimiters and re-test
- [x] Highlight successful parsing

---

## Phase 7: Spreadsheet Configuration - Part 3 (Time & Count Selection)

### 7.1 Parsed Data Display
- [x] Display parsed chromatographic data structure
- [x] Show all available data points from parsed result
- [x] Create UI for selecting Time column/field
- [x] Create UI for selecting Count column(s)/field(s)
- [x] Support multiple count selections

### 7.2 Count Naming
- [x] Allow user to name each selected count
- [x] Create name input fields for each count
- [x] Validate count names (unique, non-empty)
- [x] Store count names in configuration
- [x] Display named counts in selection UI

### 7.3 Metadata Column Selection
- [x] Display all available metadata columns from spreadsheet
- [x] Create UI for selecting which metadata columns to include in database
- [x] Allow multiple column selection (checkboxes)
- [x] Explain benefits of column selection (efficiency, faster search)
- [x] Store selected metadata columns in configuration
- [x] Validate at least one metadata column selected (optional, can be empty)

### 7.4 Configuration Validation
- [x] Validate that Time selection is valid
- [x] Validate that at least one Count is selected
- [x] Validate that all selections are from parsed data
- [x] Check data type compatibility (Time should be numeric)
- [x] Display validation errors clearly

### 7.5 Configuration Acceptance
- [x] Create "Accept Configuration" button
- [x] Perform final validation before acceptance
- [x] Save configuration to file
- [x] Update application state (configuration complete)
- [x] Enable "Enter Visualizer" button on main screen
- [x] Display success message

---

## Phase 8: Configuration Persistence

### 8.1 Configuration Saving
- [x] Implement save configuration to file
- [x] Create configuration file format/structure
- [x] Save delimiter settings
- [x] Save column mappings
- [x] Save count names and selections
- [x] Save as default configuration option

### 8.2 Configuration Loading
- [x] Implement load saved configuration
- [x] Load default configuration on startup
- [x] Allow user to select saved configuration
- [x] Validate loaded configuration against current spreadsheet
- [x] Handle configuration versioning/migration

### 8.3 Settings Persistence
- [x] Save last loaded spreadsheet path
- [x] Save window size/position preferences
- [x] Save default configuration reference
- [x] Implement settings file management
- [x] Load settings on application startup

---

## Phase 9: Data Processing & Storage

### 9.1 Chunked CSV Processing
- [x] Implement chunked CSV reading (process in batches)
- [x] Detect dataset size and choose processing strategy
- [x] Use pandas chunksize for memory-efficient processing
- [x] Implement progress reporting during processing
- [x] Handle large files (millions to billions of rows)
- [x] Support background processing with UI updates

### 9.2 Data Parsing & Extraction
- [x] Parse rows using configured delimiters (chunked)
- [x] Extract Compound ID from configured column
- [x] Extract only selected metadata columns (from Phase 7.3)
- [x] Extract Time and Count data for each compound
- [x] Handle parsing errors gracefully (skip invalid rows with warning)
- [x] Track processing statistics (successful, skipped, errors)

### 9.3 Database Storage (SQLite)
- [x] Create SQLite database schema for compounds
- [x] Store compound metadata in indexed columns (only selected columns)
- [x] Store chromatographic data points in separate table
- [x] Create indexes on searchable metadata columns
- [x] Implement batch inserts for efficiency
- [x] Support both in-memory (small datasets) and database (large datasets) modes

### 9.4 Data Validation & Cleaning
- [x] Validate Time values (numeric, reasonable range)
- [x] Validate Count values (numeric, non-negative)
- [x] Handle missing or invalid data points
- [x] Skip invalid rows with detailed error logging
- [x] Report data quality issues to user
- [x] Store validation results and statistics

### 9.5 Database Building & Indexing
- [x] Build database from processed chunks
- [x] Create indexes on all selected metadata columns
- [x] Create compound ID index for fast lookup
- [x] Optimize database for query performance
- [x] Provide database build progress and completion status
- [x] Handle database file management (location, cleanup)

---

## Phase 10: Chromatogram Visualizer - Part 1 (Basic Plotting)

### 10.1 Visualizer Window
- [x] Create visualizer window/dialog
- [x] Design window layout (plot area, controls panel)
- [x] Implement window sizing and resizing
- [x] Add navigation back to main screen

### 10.2 Basic Plotting
- [x] Integrate plotting library (matplotlib)
- [x] Create basic Count vs Time plot
- [x] Plot single compound's data
- [x] Implement interactive features (zoom, pan)
- [x] Add axis labels and title
- [x] Display compound ID in plot title

### 10.3 Count Series Selection
- [x] Create UI for selecting which count(s) to display
- [x] Implement count series toggle/selection
- [x] Plot multiple count series on same plot (different colors)
- [x] Add legend for count series
- [x] Update plot when count selection changes

---

## Phase 10.5: On-Demand Processing & Managed Bulk Databases

**Goal:** Default workflow = spreadsheet + config → visualizer → parse/plot per compound on demand. Optional bulk SQLite build lives under `output/databases/` with create/load/delete UI. Enter visualizer without prior bulk processing.

### 10.5.1 Roadmap & project layout
- [x] Mark Phase 10 checklist complete (implemented in codebase)
- [x] Add `output/databases/` managed folder (with `.gitkeep`)
- [x] Ignore generated `*.db` / WAL/SHM under that folder in `.gitignore`
- [x] Add `src/core/database_library.py`: project root resolution, `ensure_databases_dir()`, `list_managed_databases()`, `allocate_new_database_path(stem)`, `delete_managed_database(path)`

### 10.5.2 Data layer
- [x] `DataProcessor.process_spreadsheet`: when `db_path` is `None`, write to `database_library.allocate_new_database_path(...)` instead of next to spreadsheet
- [x] Add `DataProcessor.parse_dataframe_row_to_compound(row, config, row_number)` for on-demand path (reuse `_process_row` + `DataParser`)

### 10.5.3 Application state & main UI
- [x] `AppState.can_enter_visualizer()`: require spreadsheet loaded + configured + config valid; **remove** requirement for `data_processed`
- [x] `AppState.get_status_message()`: reflect on-demand vs bulk database messaging
- [x] Replace main **Process Data** button with **Create / Load database** (opens manage dialog)
- [x] Enable **Create / Load database** when spreadsheet loaded + configured + config valid (allow repeat visits; not gated on `data_processed`)
- [x] `MainScreen._on_enter_visualizer`: pass `SpreadsheetLoader` into visualizer

### 10.5.4 Bulk create dialog (existing `ProcessDataDialog`)
- [x] Title/copy: bulk create is optional / large-file warning in parent manage UI
- [x] Use managed output path for `_start_processing` / summary text (`output/databases/…`)

### 10.5.5 `DatabaseManageDialog` (new)
- [x] Modal dialog with **Create database** tab: large-file warning copy, confirm, then `wait_window(ProcessDataDialog)` on main
- [x] **Load database** tab: `CTkComboBox` of `list_managed_databases()`, **Load** sets `app_state.set_data_processed(True, path)`, **Delete** with confirmation removes file (+ WAL/SHM) and refreshes list
- [x] Optional **Clear active database** (unset `database_path` / `data_processed` without deleting file)

### 10.5.6 Chromatogram visualizer (on-demand)
- [x] Constructor accepts `loader: SpreadsheetLoader`
- [x] `_resolve_database_path`: only `app_state.database_path` if file exists (remove implicit `{stem}_database.db` beside spreadsheet)
- [x] **DB mode:** existing `DataStore` + list from DB
- [x] **Spreadsheet mode:** compound list from `loader.current_data` + `config.compound_id_column` (unique, order-preserving; cap list display as today)
- [x] **Process data** button (spreadsheet mode): find row for selected ID, `parse_dataframe_row_to_compound`, show errors, cache `Compound`, redraw
- [x] **Clear memory cache** button (spreadsheet mode): evict in-memory parsed compounds (FIFO cap e.g. 32)

### 10.5.7 Documentation & cleanup
- [x] Update **Current Status** / **Next Steps** at bottom of `ROADMAP.md`
- [x] Run `py_compile` / fix lints on touched files

---

## Phase 11: Chromatogram Visualizer - Part 2 (Search Functionality)

### 11.1 Query Builder Interface
- [x] Create visual query builder UI
- [x] Support field selection dropdown (all selected metadata columns)
- [x] Support operators: =, !=, >, <, >=, <=, contains, starts with, ends with
- [x] Support value input (text, numeric, date based on field type)
- [x] Support AND/OR logic between conditions
- [x] Allow adding/removing conditions dynamically
- [x] Display query structure visually
- [x] Create "Search" and "Clear" buttons

### 11.2 Search Logic & Database Queries
- [x] Convert query builder conditions to SQL queries
- [x] Execute queries against SQLite database with indexes
- [x] Handle different data types (text, numeric, date)
- [x] Support case-sensitive and case-insensitive text searches
- [x] Return matching compound IDs efficiently
- [x] Handle empty search results with user feedback
- [x] Optimize queries for performance (use indexes)

### 11.3 Search Results Display (Virtual Scrolling)
- [x] Implement virtual scrolling list widget
- [x] Display matching compounds with selected metadata columns
- [x] Show compound ID and relevant metadata in results
- [x] Render only visible items (20-50 at a time)
- [x] Load more items as user scrolls
- [x] Implement result selection (checkboxes for multiple selection)
- [x] Add "Select All" / "Select None" functionality
- [x] Highlight selected compounds
- [x] Display result count and status
- [x] Support secondary filtering of results (optional)

---

## Phase 12: Chromatogram Visualizer - Part 3 (Multi-Compound Plotting)

**Implemented in** `chromatogram_visualizer_window.py` (table + **Plot selected** / **Clear plot**, overlay traces, count-series toggles, pick-to-highlight).

### 12.1 Compound Selection & Plotting
- [x] Implement plot selected compound(s) functionality
- [x] Plot single compound when selected
- [x] Plot multiple compounds on same plot (overlay)
- [x] Use different colors/styles for different compounds (distinct color per trace/series; shared solid line style)
- [x] Update plot when selection changes (`<<TreeviewSelect>>` → deferred `_apply_plot_from_table_selection`)
- [x] Clear plot when no compounds selected (empty table selection clears axes; trace/background click deselects and clears)

### 12.2 Plot Management
- [x] Add "Clear Plot" functionality
- [x] Implement plot refresh/update (`_redraw_plot` on count toggles and table selection)
- [x] Add plot export functionality (**Export plot…** → PNG / PDF / SVG via `Figure.savefig`)

### 12.3 User Experience
- [x] Provide feedback for user actions (status label, messageboxes, empty-plot hints)
- [x] Handle errors gracefully
- [x] Add tooltips/help text (`widget_tooltip.py`; hover tips on visualizer controls + table)

---

## Phase 13: Documentation & Polish

### 13.1 User Documentation
- [x] User-facing docs consolidated in **README.md** (no separate manual; GitHub repo is the main resource)
- [x] Document workflow and features (succinct scientist-focused README)
- [x] Add tooltips and help text in UI (chromatogram visualizer; README covers rest)
- [x] Example spreadsheets — provided by maintainer outside the repo (not in scope)
- [x] Document file format requirements (README **Data file requirements**)

### 13.2 Code Documentation
- [x] Ensure all modules have docstrings (`src/` modules include module docstrings)
- [x] Document configuration file format ([docs/CONFIGURATION.md](docs/CONFIGURATION.md); `config/default_config.json.example` aligned with `SpreadsheetConfig`)

### 13.3 README & Setup
- [x] Update README with installation instructions
- [x] Document dependencies and setup (Quick start + link to `docs/DEPENDENCIES.md`)
- [x] Add usage examples (workflow section)

---

## Phase 14: Deployment Preparation

**Goal:** Package and ship v1 alongside the paper—not blocked on Phase 15.

### 14.1 Executable Creation
- [x] Packaging tool: **PyInstaller** (one-folder `dist/LC-Seq/`, windowed `LC-Seq.exe`)
- [x] Build config: `lc_seq.spec`, `scripts/build_windows.ps1`, [docs/BUILD.md](docs/BUILD.md)
- [x] Frozen paths: `src/core/app_paths.py` — `config/`, `output/`, `logs/` beside the `.exe`
- [x] Test executable on target Windows system (verified: fast launch, dependencies OK)
- [x] Verify dependencies in packaged build (matplotlib, CTk, pandas, DB workflow)
- [x] File size / startup: ~118 MB folder; startup fast (note in release when publishing)

### 14.2 Distribution
- [x] GitHub release structure: tag `vX.Y.Z`, asset `release/LC-Seq-vX.Y.Z-windows.zip` ([docs/RELEASE.md](docs/RELEASE.md))
- [x] Source distribution: tagged `main`, `requirements.txt`, README, LICENSE, docs on release commit
- [x] Installation instructions: [docs/INSTALL.md](docs/INSTALL.md); README **Install (Windows executable)** section
- [ ] Test download and setup process (maintainer: fresh extract from zip per RELEASE.md §5)
- [x] Release notes: [CHANGELOG.md](CHANGELOG.md) v1.0.0; copy into GitHub Release body when publishing

### 14.3 Release smoke test
- [ ] Install and launch on a clean Windows machine (or VM)
- [ ] Run one representative workflow end-to-end in the built executable
- [ ] Fix any packaging-only issues (missing DLL, wrong paths, etc.)
- [ ] Publish release notes and tagged GitHub release

---

## Phase 15: Post-Launch Testing & Hardening (optional)

**Goal:** Deeper quality work **after** v1 and the paper—when you want more confidence, coverage, or polish. Not required to ship. The app is already usable from day-to-day work; treat this as a backlog.

### 15.1 Workflows & state
- [ ] Regression pass: Load → Configure → Create/Load database → Visualize → Search → Plot → Export
- [ ] State transitions (new spreadsheet, switch DB, clear active DB, restart app, config persistence)
- [ ] Additional spreadsheet formats / sheet layouts / variant columns (beyond what you already use)

### 15.2 Edge cases & validation
- [ ] Empty, corrupt, or locked files; malformed chromatogram rows
- [ ] Invalid or incomplete configuration; recovery without restarting the app
- [ ] Missing or deleted database file while UI is open
- [ ] Tighten validation messages anywhere still vague or technical

### 15.3 Automated tests
- [ ] Expand unit tests (parsing, config, metadata search, data models)
- [ ] Add integration tests for load/configure/visualize/search paths
- [ ] Improve coverage for `AppState` and database workflows

### 15.4 Broader acceptance
- [ ] Structured test matrix with collaborator or lab data
- [ ] Log review after induced failures (ensure errors are debuggable)
- [ ] Collect feedback and iterate

---

## Future Enhancements (Post-MVP)

These features are planned for future development but are not part of the minimum viable product:

- Multi-plot view (side-by-side plots)
- Plot overlay toggle functionality
- Advanced search filters
- Data export functionality
- Cross-platform installer development
- Additional visualization options
- Batch processing capabilities
- Data analysis tools

---

## Development Notes

- **Follow AGENT_INSTRUCTIONS.md** for all development work
- **Commit frequently** after completing each task or logical unit
- **Test as you go** - don't wait until the end
- **Ask questions** if requirements are unclear
- **Update this roadmap** if changes are needed (with user approval)

---

## Current Status

**Phase**: Phase 12 complete — release path is Phases 13–14  
**Last Updated**: 2026-05-19  
**Next Steps**: Phase 14.2 download test → Phase 14.3 (publish GitHub Release) → ship v1

**Key Design Decisions**:
- **Primary workflow**: Spreadsheet + valid configuration → enter visualizer → **parse/plot on demand** per compound (no bulk SQLite required).
- **Optional bulk SQLite**: Full-database build is a **special** path; databases are stored under `output/databases/` with create/load/delete management UI.
- **Scalability**: Chunked processing remains for bulk CSV builds; on-demand parses one row at a time from the in-memory dataframe.
- **Storage**: SQLite retained for optional indexed bulk storage and future search (Phase 11).
- **Metadata Selection**: Users select which metadata columns to include during configuration (Phase 7.3).
- **Search**: Full-featured query builder with AND/OR logic, multiple operators (Phase 11).
- **Results Display**: Virtual scrolling for efficient rendering of large result sets (Phase 11.3).
