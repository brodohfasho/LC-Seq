# Dependency Choices and Rationale

This document explains the dependency choices made for the LC-Seq application.

## GUI Framework: CustomTkinter

**Choice**: `customtkinter>=5.2.0`

**Rationale**:
- Modern, professional-looking UI with built-in dark/light themes
- Built on top of tkinter (Python standard library), ensuring compatibility
- Easy to learn and use, good for novice developers
- Active development and community support
- Cross-platform compatible
- No additional licensing concerns (MIT license)
- Good performance for desktop applications

**Alternatives Considered**:
- **tkinter**: Built-in but looks dated, requires significant styling work
- **PyQt/PySide**: More powerful but has licensing considerations (GPL or commercial)
- **wxPython**: Good but less modern appearance

## Data Processing: Pandas

**Choice**: `pandas>=2.0.0`

**Rationale**:
- Industry standard for data manipulation and analysis
- Excellent Excel and CSV file support
- Powerful data structures (DataFrame) perfect for spreadsheet data
- Extensive documentation and community support
- Efficient handling of large datasets
- Built-in data validation and cleaning tools

## Excel Support: openpyxl and xlrd

**Choices**: 
- `openpyxl>=3.1.0` (for .xlsx files)
- `xlrd>=2.0.1` (for legacy .xls files)

**Rationale**:
- **openpyxl**: Modern, actively maintained, handles .xlsx format (most common)
- **xlrd**: Required for legacy .xls file support
- Both work seamlessly with pandas
- No additional dependencies needed

## Plotting: Matplotlib

**Choice**: `matplotlib>=3.7.0`

**Rationale**:
- Most widely used Python plotting library
- Excellent documentation and examples
- Highly customizable for scientific plots
- Good interactive features (zoom, pan, hover)
- Stable and well-tested
- Easy to package with executables
- Supports multiple backends

**Alternatives Considered**:
- **Plotly**: More interactive but larger dependency, more complex packaging
- **Bokeh**: Good for web apps, overkill for desktop

## Testing: Pytest

**Choices**:
- `pytest>=7.4.0`
- `pytest-cov>=4.1.0`

**Rationale**:
- Industry standard Python testing framework
- Simple, intuitive syntax
- Excellent fixture system
- Good test discovery
- Coverage reporting built-in
- Active development and community

## Code Quality Tools

### Black (Formatter)
**Choice**: `black>=23.7.0`

**Rationale**:
- Uncompromising code formatter
- Eliminates style debates
- Consistent code style across project
- Widely adopted in Python community

### Flake8 (Linter)
**Choice**: `flake8>=6.1.0`

**Rationale**:
- Fast, reliable linting
- Catches common errors and style issues
- Configurable rules
- Good integration with IDEs

### MyPy (Type Checking)
**Choice**: `mypy>=1.5.0`

**Rationale**:
- Static type checking for Python
- Helps catch errors early
- Improves code documentation
- Optional typing (won't break untyped code)

## Python version

**Minimum for the desktop app:** Python 3.10+ (recommended; required for a smooth Rust/`maturin` developer setup).  
Older notes mentioning 3.8 are obsolete for the v2 analysis stack.

## Analysis / build extras (developers)

| Dependency | Role |
|------------|------|
| **Rust + maturin** | Build the `lcseq` extension (`LC-Seq-New-master/`) — see [DEVELOPER_SETUP.md](DEVELOPER_SETUP.md) |
| **scipy** | Python fallback for Modern peak picking when Rust is not built |
| **graphviz** (Python + system `dot`) | Optional higher-quality pedigree figure export |

End users of the Windows release zip do **not** need these; the zip bundles `lcseq`.

## Summary

All application dependencies are:

- Open source with permissive licenses
- Actively maintained
- Well-documented
- Compatible with packaging tools (PyInstaller, etc.)
- Suitable for Windows-first desktop deployment
