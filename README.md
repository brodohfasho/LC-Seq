# LC-Seq: Chromatographic Data Analysis Application

LC-Seq is a desktop application for analyzing chromatographic data from spreadsheets. It provides tools to load, configure, parse, and visualize time-series chromatographic data with flexible delimiter handling and interactive plotting.

## Features

- **Spreadsheet Loading**: Support for Excel (.xlsx, .xls) and CSV files
- **Flexible Data Parsing**: Configurable delimiter sequences for parsing chromatographic data
- **Interactive Visualization**: Plot Count vs Time data with zoom, pan, and multi-series support
- **Compound Search**: Search compounds by any column field with partial matching
- **Configuration Persistence**: Save and reuse spreadsheet configurations
- **Multi-Compound Plotting**: Overlay multiple compounds on the same plot

## Requirements

- Python 3.8 or higher
- Windows (initial release; cross-platform support planned)

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/brodohfasho/LC-Seq.git
cd LC-Seq
```

### 2. Set Up Virtual Environment

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

## Usage

### Running the Application

```bash
python src/main.py
```

### Workflow

1. **Load Spreadsheet**: Click "Load Spreadsheet" and select your Excel or CSV file
2. **Configure Spreadsheet**: 
   - Select the Compound ID column
   - Select the Chromatographic Data column
   - Configure delimiters and test parsing
   - Select Time and Count columns from parsed data
   - Name your count series
3. **Visualize**: Enter the Chromatogram Visualizer to plot and search your data

## Project Structure

```
LC-Seq/
├── src/                # Source code
│   ├── core/          # Core application logic
│   ├── models/        # Data models
│   ├── ui/            # User interface components
│   └── utils/         # Utility functions
├── tests/             # Test files
├── config/            # Configuration files
├── data/              # Sample data (gitignored)
├── docs/              # Documentation
├── requirements.txt   # Python dependencies
└── README.md          # This file
```

## Development

### Running Tests

```bash
pytest
```

### Code Formatting

```bash
black src/ tests/
```

### Linting

```bash
flake8 src/ tests/
```

## License

See LICENSE file for details.

## Contributing

This is currently a personal project. Contributions and suggestions are welcome!

## Roadmap

See [ROADMAP.md](ROADMAP.md) for detailed development phases and progress.
