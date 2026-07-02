# Peak picking

## What this does

**Pick peaks** finds bumps in your chromatogram that are large enough to be real signal, not random noise.

## Baseline (noise floor)

The program first estimates the **baseline** — the typical background count when no peak is present. It uses the same method as the Rust analysis engine: remove very high points, then take the median of what is left.

## Significance (α)

Each peak gets a **p-value** from two tests: apex height and integrated area (rolling baseline, NB/Poisson). **Both** must be significant: each p-value below **α/2** (Bonferroni). The table shows the smaller of the two.

**α (alpha)** is your cutoff. Common choices:

- **0.001** — strict (fewer peaks)
- **0.05** — looser (more peaks)

## Quality filters (prominence and % area)

After statistical detection, peaks must also meet:

- **Min prominence** — height above the higher adjacent valley (counts)
- **Min % area** — share of total detected peak area

Peaks below these cutoffs are hidden from the plot and table but remain in the full detected set. Set either threshold to **0** to disable it.

After **Analyze lineage**, peaks assigned to a **null truncation** tier can be shown even when they fail prominence / % area filters.

## What you see on the plot

- Colored markers on displayed peak tops only
- Orange shading between valleys (integration window)

## Tips

- Pick peaks on **one compound** and **one count channel** at a time for clearest results.
- If no peaks appear, try a larger α or check that the count channel has signal.
