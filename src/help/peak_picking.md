# Peak picking

## Where peak picking lives

- **Chromatogram Visualizer** — expand the **Peak analysis** panel below the plot. Use **Pick peaks** on one or more selected compounds.
- **Library Analysis → RT assignment** — the same algorithms and quality filters run library-wide when you **Run RT assignment** (pedigree or direct pick).

Both places share the **Modern** and **Old-school** algorithms described below.

## What peak picking does

**Pick peaks** finds bumps in your chromatogram that are large enough to be real signal, not random noise. Detected peaks get retention time, height, integrated area, prominence, and (in modern mode) significance p-values.

## Peak picking algorithm

Choose **Modern** or **Old-school** from the algorithm menu. Only the active mode’s parameters apply; the inactive column is greyed out.

### Modern (recommended)

Uses the same statistical engine as the Rust analysis core:

1. Estimate **baseline** μ and σ (median after removing high points).
2. Find local maxima above baseline.
3. For each candidate, compute p-values for **apex height** and **integrated area** (rolling baseline, NB/Poisson).
4. Keep peaks where **both** p-values are below **α/2** (Bonferroni). The results table shows the smaller of the two.

**Peak significance α** — your cutoff. Common choices:

- **0.001** — strict (fewer peaks)
- **0.05** — looser (more peaks)

### Old-school (legacy notebooks)

Matches historical scipy + Gaussian workflows:

1. Gate candidates by **Min height factor** (fraction of trace maximum).
2. Fit a Gaussian in a **Gaussian fit width** window around each candidate.
3. Reject fits with **Max Gaussian σ** too wide.
4. Ignore signal before **Minimum RT** (peaks below this RT are never considered).

Use old-school when you need parity with legacy notebook parameters. **Minimum RT** is a picker cutoff only — it is **not** the **Null RT Threshold** on Library Analysis (see glossary / export bundle help).

## Quality filters (both modes)

After detection, peaks must also meet:

- **Min prominence** — height above the higher adjacent valley (counts)
- **Min % area** — share of total detected peak area

Peaks below these cutoffs are hidden from the plot and table but remain in the full detected set. Set either threshold to **0** to disable it.

These same filters apply to **Library Analysis** scan metrics, RT assignment, and pedigree evaluation when configured on the RT assignment sidebar.

After **Analyze lineage**, peaks assigned to a **null truncation** tier can be shown even when they fail prominence / % area filters.

## What you see on the plot

- Colored markers on displayed peak tops
- Optional orange shading between valleys when **Show integration** is on (see **Peak integration** help)

## Export

In the Chromatogram Visualizer peak panel, use **Export CSV** to save RT, height, area, prominence, and p-value for each displayed peak.

Library-wide RT and DEL-cycle tables are exported from **Library Analysis → RT assignment** (**Export RTs…**, **Export analysis bundle…**).

## Tips

- Pick peaks on **one compound** and **one count channel** at a time for clearest results.
- If no peaks appear in modern mode, try a larger α or check that the count channel has signal.
- If old-school finds nothing, check **Minimum RT** and **Min height factor** against your trace scale and time unit.
