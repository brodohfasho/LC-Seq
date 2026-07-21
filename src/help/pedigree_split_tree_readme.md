# Pedigree visualization figure

How to read the **Pedigree visualization** tab (null-truncation pedigree).  
This is **not** the **Split-tree visualization** tab (combinatorial BB tree).

## Question at each node

Did class members show a significant peak **after** the parent RT (+ **Null RT threshold**)? Same logic as lineage, run library-wide in **Pedigree** RT mode.

## Node types

| Tier | Type | Example | Meaning |
|------|------|---------|---------|
| 0 | Root | `ROOT` | All-null |
| 1…N−1 | Class | `DNvl` or `A+B` | Non-null BB sequence at that depth |
| N | Compound | `Null-A-B` | Full product |

Large libraries create many class nodes per ring.

## Layout & colors

Centre = root; outward rings = tiers. Graphviz `twopi` when available; otherwise matplotlib tier-ring.

| Colour | Meaning |
|--------|---------|
| Grey | Root |
| Light / dark green | Passed class / compound |
| Red | Failure (signal, no valid peak past parent) |
| Yellow | Insufficient data |

Pruned descendants of failed parents are not drawn.

## Display controls

| Control | Effect |
|---------|--------|
| **Max tier shown** | Hide outer rings (default often hides compound leaves) |
| **Show failed trim points** | Off = passed-only (cleaner); auto-off if > ~500 nodes |
| **Show RT on labels** | Append chosen RT to passed nodes |
| **Refresh tree** | Apply options |

Tier summary and **Export pedigree CSV** always include all evaluated tiers; filters affect the figure only.

## Large libraries

Use passed-only + lower max tier for an overview; use CSV / tier counts for detail. Compare **`product_prominence.csv`** (pedigree RT) with bulk QC tallest-peak metrics carefully.
