# Understanding the pedigree split-tree figure

This page explains how LC-Seq builds the library pedigree image, what each node means, and how to make large libraries readable.

## What pedigree analysis does

Pedigree analysis evaluates your **entire library** against the DEL **null-truncation tree**. For each equivalence class at every coupling cycle it asks:

> Did chromatograms for members of this class show a statistically significant peak **after** the parent’s retention time (plus tolerance)?

The same logic powers **lineage analysis** for a single compound; pedigree runs it **library-wide**.

## What each node is (not “one dot per building block”)

| Tier | Node type | Label example | Meaning |
|------|-----------|---------------|---------|
| 0 | Root class | `ROOT` | All-null foundation truncate |
| 1…N−1 | Class | `DNvl` or `A+B` | Non-null BB sequence at that depth (`+` joins BBs) |
| N | Compound | `Null-A-B` | One full product (positional display with `-`) |

Tier **1** is closest to “one node per building block.” Higher tiers are **ordered BB combinations** allowed at that library depth. The tree is built from all BBs observed at each position, so large libraries produce **many** class nodes per ring.

## Layout: split-tree

- **Centre** = tier 0 (root)
- **Outward rings** = coupling cycles (tier 1, 2, …)
- **Edges** = parent → child in the null-truncation pedigree (a child may have multiple parents)

**Graphviz** (when installed) uses the `twopi` engine — the intended split-tree layout. **Without Graphviz**, LC-Seq draws a **matplotlib tier-ring preview**: nodes are spaced evenly on each ring, which can look like a dense “web” on large libraries. Install Graphviz (see `docs/DEVELOPER_SETUP.md`) for the native layout.

## Colours

| Colour | Meaning |
|--------|---------|
| Grey | Root (all-null) |
| Light green | Passed **class** |
| Dark green | Passed **full compound** |
| Red | **Synthesis failure** — signal existed but no valid peak past parent |
| Yellow | **Insufficient data** — not enough sequencing signal to call peaks |

Nodes **pruned** because a parent failed are **not drawn** (their descendants are cut off).

## Tree display controls (this tab)

| Control | Effect |
|---------|--------|
| **Max tier shown** | Hides outer rings. Default hides the final compound-leaf tier (often very dense). Lower to tier 0–1 for a BB overview. |
| **Show failed trim points** | When off, only **passed** nodes appear (cleaner on large libraries). Auto-turns off when visible nodes exceed ~500. |
| **Show RT on labels** | Appends chosen retention time to passed node labels. |
| **Refresh tree** | Re-render after changing the options above. |

The **tier summary** cards and **pedigree CSV** always include all evaluated tiers; display filters affect only the figure.

## How the image is generated (technical)

1. Load compounds and build a chromatogram map (count channel, time unit).
2. Rust `evaluate_library` walks the pedigree DAG tier by tier.
3. Visible nodes are filtered: `passed` OR (`evaluated` AND show-failed).
4. Render via `lcseq.render.render_pruned_tree` (Graphviz) or matplotlib fallback.

## Reading the figure on large libraries

- Use **passed-only** and a **lower max tier** for an interpretable overview.
- Use **tier summary** counts and **Export pedigree CSV** for full detail.
- **Product peak prominence** (when shown) measures signal at pedigree-validated product RT — compare with bulk Library Data S/N, which uses the tallest significant peak and may not be the product.

## Related help

Use **Help** on the Pedigree tab for pedigree analysis settings and the DEL cycle bundle glossary.
