# Spreadsheet Configuration and Database Build

Users must configure their input spreadsheet before running analyses or visualizing chromatograms. This program was built to accept data in many different formats and accept a variety of metadata for searching or plotting, however it does expect you to set up your spreadsheet such that each compound is one row and the chromatographic data is delimited (e.g. time;count,time;count,etc.) and kept in a single cell.

## Spreadsheet Configuration Wizard

Each step requires the user to click a **big red button** to validate their current data setup before moving on.

1. Map columns to your compound ID's, chromatographic data, and if you have any variants (e.g. linear vs cyclized).
2. Select the appropriate delimiters to parse your data. We had two counts (all counts and deduplicated counts) so we needed three delimiters (e.g. time;count:deduplicatedcount, etc.). Leave delimiter 3 blank if you don't need it.
3. Assign each set of parsed data to time and counts. Select all the counts you'd like to take forward (if applicable).
4. Select metadata to carry forward. This is primarily for advanced searching in the chromatogram visualizer. More metadata will reduce performance, so only take forward data you want to use for searching.
5. Select the amount of library cycles, map columns corresponding to building block identities (per cycle), and (optionally) input an index CSV to assign numbers in the split-tree analysis. This file should be two columns: Name (BB names) and Index (numbering 1-N).
6. Accept configuration and move on to Create / Load database.

## Create / Load database

1. Build a Full Database (recommended) or Index Database. Full databases pre-parse the chromatographic data. They are larger files, but execute all the calculations faster. Use Full Databases if memory allows.
2. Load old database files. The user can also load the last database file by clicking the "database button" underneath the "LC-Seq" title in the main menu.
3. After successfully building the database, proceed to the chromatogram visualizer or library data module.