# LC-Seq Development Roadmap

This roadmap outlines the development phases for the LC-Seq chromatographic data analysis application. Follow this roadmap procedurally, completing each phase before moving to the next.

## Project Overview

**Application Type**: Desktop application (Python-based, cross-platform capable, starting with Windows focus)  
**Core Functionality**: Load, configure, and visualize chromatographic data from spreadsheets  
**Target Users**: Scientists and researchers analyzing chromatographic time-series data

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
- [ ] Design Compound data model (ID, metadata columns, chromatographic data)
- [ ] Design ChromatographicDataPoint model (time, count values)
- [ ] Design SpreadsheetConfig model (delimiters, column mappings, parsing rules)
- [ ] Design AppSettings model (default configs, last loaded file, user preferences)
- [ ] Implement data validation logic for all models

### 2.2 Configuration Management
- [ ] Design configuration file format (JSON or YAML)
- [ ] Implement configuration loader/saver
- [ ] Create default configuration template
- [ ] Implement configuration validation
- [ ] Add error handling for corrupted/invalid configs

### 2.3 Data Parsing Logic
- [ ] Implement delimiter parsing engine (handles multiple delimiters in sequence)
- [ ] Create parser for chromatographic data strings
- [ ] Implement parsing preview/test functionality
- [ ] Add error handling for malformed data
- [ ] Create unit tests for parsing logic

---

## Phase 3: Main Screen UI

### 3.1 Main Window Layout
- [ ] Design main window structure
- [ ] Implement window title and basic styling
- [ ] Create primary "Enter Chromatogram Visualizer" button
- [ ] Create "Load Spreadsheet" button
- [ ] Create "Configure Spreadsheet" button
- [ ] Implement button state management (disable visualizer until ready)

### 3.2 State Management
- [ ] Implement application state tracking (spreadsheet loaded, configured)
- [ ] Create state change handlers
- [ ] Implement button enable/disable logic based on state
- [ ] Add visual feedback for button states
- [ ] Display status messages for user guidance

### 3.3 Navigation Framework
- [ ] Design navigation system between screens
- [ ] Implement screen switching logic
- [ ] Create base window class for consistency
- [ ] Add window close handlers and cleanup

---

## Phase 4: Spreadsheet Loading

### 4.1 File Selection
- [ ] Implement file dialog for spreadsheet selection
- [ ] Support Excel (.xlsx, .xls) and CSV file formats
- [ ] Add file format validation
- [ ] Display selected file path to user
- [ ] Store last loaded file path in settings

### 4.2 Data Loading
- [ ] Implement spreadsheet reading (pandas)
- [ ] Handle different Excel sheet selection (if multiple sheets)
- [ ] Load data into memory with error handling
- [ ] Validate basic file structure (has rows, has columns)
- [ ] Display loading progress/status

### 4.3 Data Validation
- [ ] Check for required columns (Compound ID, Chromatographic Data)
- [ ] Validate data types where possible
- [ ] Display validation errors to user
- [ ] Allow user to retry or select different file

---

## Phase 5: Spreadsheet Configuration - Part 1 (Column Selection)

### 5.1 Configuration Screen Layout
- [ ] Create configuration window/dialog
- [ ] Display loaded spreadsheet column headers
- [ ] Create UI for selecting Compound ID column
- [ ] Create UI for selecting Chromatographic Data column
- [ ] Add validation for column selections

### 5.2 Column Selection Logic
- [ ] Implement column selection handlers
- [ ] Validate that selected columns exist
- [ ] Store column selections in configuration
- [ ] Display selected columns to user
- [ ] Allow user to change selections

---

## Phase 6: Spreadsheet Configuration - Part 2 (Delimiter Configuration)

### 6.1 Delimiter Selection UI
- [ ] Create delimiter configuration interface
- [ ] Allow user to specify delimiter sequence (order matters)
- [ ] Support common delimiters (comma, semicolon, colon, tab, etc.)
- [ ] Allow custom delimiter input
- [ ] Display delimiter sequence visually

### 6.2 Parsing Preview
- [ ] Implement test data input field (sample from spreadsheet)
- [ ] Create "Test Parse" button
- [ ] Display parsed results in preview table/grid
- [ ] Show parsing errors if any
- [ ] Allow user to adjust delimiters and re-test
- [ ] Highlight successful parsing

---

## Phase 7: Spreadsheet Configuration - Part 3 (Time & Count Selection)

### 7.1 Parsed Data Display
- [ ] Display parsed chromatographic data structure
- [ ] Show all available data points from parsed result
- [ ] Create UI for selecting Time column/field
- [ ] Create UI for selecting Count column(s)/field(s)
- [ ] Support multiple count selections

### 7.2 Count Naming
- [ ] Allow user to name each selected count
- [ ] Create name input fields for each count
- [ ] Validate count names (unique, non-empty)
- [ ] Store count names in configuration
- [ ] Display named counts in selection UI

### 7.3 Configuration Validation
- [ ] Validate that Time selection is valid
- [ ] Validate that at least one Count is selected
- [ ] Validate that all selections are from parsed data
- [ ] Check data type compatibility (Time should be numeric)
- [ ] Display validation errors clearly

### 7.4 Configuration Acceptance
- [ ] Create "Accept Configuration" button
- [ ] Perform final validation before acceptance
- [ ] Save configuration to file
- [ ] Update application state (configuration complete)
- [ ] Enable "Enter Visualizer" button on main screen
- [ ] Display success message

---

## Phase 8: Configuration Persistence

### 8.1 Configuration Saving
- [ ] Implement save configuration to file
- [ ] Create configuration file format/structure
- [ ] Save delimiter settings
- [ ] Save column mappings
- [ ] Save count names and selections
- [ ] Save as default configuration option

### 8.2 Configuration Loading
- [ ] Implement load saved configuration
- [ ] Load default configuration on startup
- [ ] Allow user to select saved configuration
- [ ] Validate loaded configuration against current spreadsheet
- [ ] Handle configuration versioning/migration

### 8.3 Settings Persistence
- [ ] Save last loaded spreadsheet path
- [ ] Save window size/position preferences
- [ ] Save default configuration reference
- [ ] Implement settings file management
- [ ] Load settings on application startup

---

## Phase 9: Data Processing & Storage

### 9.1 Data Parsing & Extraction
- [ ] Parse all rows using configured delimiters
- [ ] Extract Time and Count data for each compound
- [ ] Handle parsing errors gracefully (skip invalid rows with warning)
- [ ] Store parsed data in memory efficiently
- [ ] Create data structure for quick access

### 9.2 Data Validation & Cleaning
- [ ] Validate Time values (numeric, reasonable range)
- [ ] Validate Count values (numeric, non-negative)
- [ ] Handle missing or invalid data points
- [ ] Report data quality issues to user
- [ ] Store validation results

### 9.3 Compound Indexing
- [ ] Create searchable index of compounds
- [ ] Index all column fields for search
- [ ] Store compound metadata efficiently
- [ ] Implement fast lookup structures

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

### 11.1 Search Interface
- [ ] Create search input field
- [ ] Create "Search" button
- [ ] Create column selection UI (which columns to search)
- [ ] Allow multiple column selection for search
- [ ] Display search interface in visualizer

### 11.2 Search Logic
- [ ] Implement partial match search algorithm
- [ ] Search across selected columns
- [ ] Handle case sensitivity (configurable)
- [ ] Return matching compounds
- [ ] Handle empty search results

### 11.3 Search Results Display
- [ ] Create results list/table
- [ ] Display matching compounds with key information
- [ ] Show compound ID and relevant metadata
- [ ] Implement result selection (single or multiple)
- [ ] Add scrollable results if many matches
- [ ] Highlight selected compounds

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

**Phase**: Phase 1 - Project Foundation & Setup (Complete)  
**Last Updated**: 2026-02-01  
**Next Steps**: Begin Phase 2 - Data Models & Core Logic
