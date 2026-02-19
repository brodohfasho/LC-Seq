# LC-Seq Development Roadmap

This roadmap outlines the development phases for the LC-Seq chromatographic data analysis application. Follow this roadmap procedurally, completing each phase before moving to the next.

## Project Overview

**Application Type**: Desktop application (Python-based, cross-platform capable, starting with Windows focus)  
**Core Functionality**: Load, configure, and visualize chromatographic data from spreadsheets  
**Target Users**: Scientists and researchers analyzing chromatographic time-series data (including DNA encoded library data)

**Workflow**:
1. Load spreadsheet (.csv containing possibly millions-billions of rows)
2. Configure spreadsheet (select columns, delimiters, time/count fields, metadata columns)
3. Build searchable database (chunked processing, SQLite storage)
4. Query database (visual query builder with complex conditions)
5. Visualize data (plot selected compounds' chromatographic data)

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
- [ ] Implement chunked CSV reading (process in batches)
- [ ] Detect dataset size and choose processing strategy
- [ ] Use pandas chunksize for memory-efficient processing
- [ ] Implement progress reporting during processing
- [ ] Handle large files (millions to billions of rows)
- [ ] Support background processing with UI updates

### 9.2 Data Parsing & Extraction
- [ ] Parse rows using configured delimiters (chunked)
- [ ] Extract Compound ID from configured column
- [ ] Extract only selected metadata columns (from Phase 7.3)
- [ ] Extract Time and Count data for each compound
- [ ] Handle parsing errors gracefully (skip invalid rows with warning)
- [ ] Track processing statistics (successful, skipped, errors)

### 9.3 Database Storage (SQLite)
- [ ] Create SQLite database schema for compounds
- [ ] Store compound metadata in indexed columns (only selected columns)
- [ ] Store chromatographic data points in separate table
- [ ] Create indexes on searchable metadata columns
- [ ] Implement batch inserts for efficiency
- [ ] Support both in-memory (small datasets) and database (large datasets) modes

### 9.4 Data Validation & Cleaning
- [ ] Validate Time values (numeric, reasonable range)
- [ ] Validate Count values (numeric, non-negative)
- [ ] Handle missing or invalid data points
- [ ] Skip invalid rows with detailed error logging
- [ ] Report data quality issues to user
- [ ] Store validation results and statistics

### 9.5 Database Building & Indexing
- [ ] Build database from processed chunks
- [ ] Create indexes on all selected metadata columns
- [ ] Create compound ID index for fast lookup
- [ ] Optimize database for query performance
- [ ] Provide database build progress and completion status
- [ ] Handle database file management (location, cleanup)

---

## Phase 10: Chromatogram Visualizer - Part 1 (Basic Plotting)

### 10.1 Visualizer Window
- [ ] Create visualizer window/dialog
- [ ] Design window layout (plot area, controls panel)
- [ ] Implement window sizing and resizing
- [ ] Add navigation back to main screen

### 10.2 Basic Plotting
- [ ] Integrate plotting library (matplotlib or plotly)
- [ ] Create basic Count vs Time plot
- [ ] Plot single compound's data
- [ ] Implement interactive features (zoom, pan)
- [ ] Add axis labels and title
- [ ] Display compound ID in plot title

### 10.3 Count Series Selection
- [ ] Create UI for selecting which count(s) to display
- [ ] Implement count series toggle/selection
- [ ] Plot multiple count series on same plot (different colors)
- [ ] Add legend for count series
- [ ] Update plot when count selection changes

---

## Phase 11: Chromatogram Visualizer - Part 2 (Search Functionality)

### 11.1 Query Builder Interface
- [ ] Create visual query builder UI
- [ ] Support field selection dropdown (all selected metadata columns)
- [ ] Support operators: =, !=, >, <, >=, <=, contains, starts with, ends with
- [ ] Support value input (text, numeric, date based on field type)
- [ ] Support AND/OR logic between conditions
- [ ] Allow adding/removing conditions dynamically
- [ ] Display query structure visually
- [ ] Create "Search" and "Clear" buttons

### 11.2 Search Logic & Database Queries
- [ ] Convert query builder conditions to SQL queries
- [ ] Execute queries against SQLite database with indexes
- [ ] Handle different data types (text, numeric, date)
- [ ] Support case-sensitive and case-insensitive text searches
- [ ] Return matching compound IDs efficiently
- [ ] Handle empty search results with user feedback
- [ ] Optimize queries for performance (use indexes)

### 11.3 Search Results Display (Virtual Scrolling)
- [ ] Implement virtual scrolling list widget
- [ ] Display matching compounds with selected metadata columns
- [ ] Show compound ID and relevant metadata in results
- [ ] Render only visible items (20-50 at a time)
- [ ] Load more items as user scrolls
- [ ] Implement result selection (checkboxes for multiple selection)
- [ ] Add "Select All" / "Select None" functionality
- [ ] Highlight selected compounds
- [ ] Display result count and status
- [ ] Support secondary filtering of results (optional)

---

## Phase 12: Chromatogram Visualizer - Part 3 (Multi-Compound Plotting)

### 12.1 Compound Selection & Plotting
- [ ] Implement plot selected compound(s) functionality
- [ ] Plot single compound when selected
- [ ] Plot multiple compounds on same plot (overlay)
- [ ] Use different colors/styles for different compounds
- [ ] Update plot when selection changes
- [ ] Clear plot when no compounds selected

### 12.2 Plot Management
- [ ] Add "Clear Plot" functionality
- [ ] Implement plot refresh/update
- [ ] Handle large datasets efficiently
- [ ] Add plot export functionality (optional for MVP)
- [ ] Optimize rendering performance

### 12.3 User Experience
- [ ] Add loading indicators for large datasets
- [ ] Provide feedback for user actions
- [ ] Handle errors gracefully
- [ ] Add tooltips/help text
- [ ] Ensure responsive UI

---

## Phase 13: Integration & State Management

### 13.1 End-to-End Flow
- [ ] Test complete workflow: Load → Configure → Visualize
- [ ] Ensure state transitions work correctly
- [ ] Verify configuration persistence across sessions
- [ ] Test with various spreadsheet formats
- [ ] Test with different data structures

### 13.2 Error Handling
- [ ] Add comprehensive error handling throughout
- [ ] Display user-friendly error messages
- [ ] Log errors for debugging
- [ ] Handle edge cases (empty files, malformed data)
- [ ] Add recovery mechanisms

### 13.3 Data Validation
- [ ] Validate data at each stage
- [ ] Provide clear validation error messages
- [ ] Allow user to correct issues
- [ ] Prevent invalid state transitions

---

## Phase 14: Testing

### 14.1 Unit Tests
- [ ] Write tests for data parsing logic
- [ ] Write tests for configuration management
- [ ] Write tests for search functionality
- [ ] Write tests for data models
- [ ] Achieve good test coverage

### 14.2 Integration Tests
- [ ] Test spreadsheet loading with various formats
- [ ] Test configuration workflow
- [ ] Test visualization with sample data
- [ ] Test search functionality
- [ ] Test state management

### 14.3 User Acceptance Testing
- [ ] Test with real user data
- [ ] Verify all requirements are met
- [ ] Test edge cases and error scenarios
- [ ] Gather feedback and iterate

---

## Phase 15: Documentation & Polish

### 15.1 User Documentation
- [ ] Create user guide/manual
- [ ] Document workflow and features
- [ ] Add tooltips and help text in UI
- [ ] Create example spreadsheets
- [ ] Document file format requirements

### 15.2 Code Documentation
- [ ] Ensure all modules have docstrings
- [ ] Document complex algorithms
- [ ] Add inline comments where needed
- [ ] Create API documentation
- [ ] Document configuration file format

### 15.3 README & Setup
- [ ] Update README with installation instructions
- [ ] Document dependencies and setup
- [ ] Add usage examples
- [ ] Include screenshots/demos
- [ ] Document known issues/limitations

---

## Phase 16: Deployment Preparation

### 16.1 Executable Creation
- [ ] Research Python packaging tools (PyInstaller, cx_Freeze)
- [ ] Create executable build configuration
- [ ] Test executable on clean Windows system
- [ ] Verify all dependencies are included
- [ ] Test file size and startup time

### 16.2 Distribution
- [ ] Create GitHub release structure
- [ ] Prepare source code distribution
- [ ] Create installation instructions
- [ ] Test download and setup process
- [ ] Prepare release notes

### 16.3 Final Testing
- [ ] Test on fresh Windows installation
- [ ] Verify all features work in executable
- [ ] Test with various user scenarios
- [ ] Fix any deployment-specific issues
- [ ] Prepare for initial release

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

**Phase**: Phase 8 - Configuration Persistence (Complete)  
**Last Updated**: 2026-02-01  
**Next Steps**: Begin Phase 9 - Data Processing & Storage

**Key Design Decisions**:
- **Scalability**: Chunked processing for large datasets (millions-billions of rows)
- **Storage**: SQLite database backend for efficient search and memory management
- **Metadata Selection**: Users select which metadata columns to include during configuration (Phase 7.3)
- **Search**: Full-featured query builder with AND/OR logic, multiple operators (Phase 11)
- **Results Display**: Virtual scrolling for efficient rendering of large result sets (Phase 11.3)

**Key Design Decisions**:
- **Scalability**: Chunked processing for large datasets (millions-billions of rows)
- **Storage**: SQLite database backend for efficient search and memory management
- **Metadata Selection**: Users select which metadata columns to include during configuration (Phase 7.3)
- **Search**: Full-featured query builder with AND/OR logic, multiple operators (Phase 11)
- **Results Display**: Virtual scrolling for efficient rendering of large result sets (Phase 11.3)
