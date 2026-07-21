# Agent instructions for LC-Seq development

Guidelines for AI agents working on the LC-Seq chromatographic data analysis application.

## Product vocabulary (use consistently)

| Concept | Name |
|---------|------|
| Main library dashboard | **Library Analysis** (not “Library Data”) |
| RT modes | **Pedigree** / **Direct pick** |
| Figures | **Pedigree visualization** / **Split-tree visualization** |
| Bundle export | **Export analysis bundle** |
| Peak pickers | **Modern** / **Old-school** (paper Methods = Old-school + Direct pick) |

“DEL” means DNA-encoded library (science domain), not a third analysis mode. Internal package `del_cycle_tree` implements the **split-tree** pipeline.

## Core principles

### Code quality
- Prefer SOLID principles, clear module boundaries, and maintainable structure
- Docstrings on modules; `# relative/path/to/file` at the top of scripts
- Do not invent generic fallback return values unless the user asks for them

### Communication
- Ask before ambiguous or destructive work
- Prefer the user’s stated scope over speculative features

### Product context
- Prefer [APPLICATION_WORKFLOW.md](APPLICATION_WORKFLOW.md), [ROADMAP.md](ROADMAP.md), in-app help under `src/help/`, and [release_checklist.md](../release_checklist.md) over archived phase plans
- Historical plans live under [archive/](archive/) — do not treat them as current requirements

### Version control
- Commit only when the user asks
- Do not push unless asked
- Use clear commit messages focused on why

### Testing
- Run relevant tests after non-trivial changes (`pytest tests/`)
- Rebuild Rust with `maturin develop --release` when touching `LC-Seq-New-master/`

## Notes

- Windows-first desktop app (CustomTkinter)
- Prioritize clarity and maintainability
- When in doubt, choose the more explicit approach and confirm with the user
