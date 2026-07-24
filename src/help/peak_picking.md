# Peak Picking

## Where

- **Chromatogram Visualizer → Peak analysis** — **Pick peaks** on selected compounds. The peak table and plot annotations follow the compound-table selection.
- **Library Analysis → RT assignment** — same algorithms for library-wide RT assignment.

## Algorithms

Choose **Modern** or **Old-school**.

### Modern

1. Estimate baseline μ and σ.
2. Find local maxima above baseline.
3. Keep peaks where height and area p-values are both < **α/2**.
4. Optionally drop peaks below **Min prominence** / **Min % area**.

Typical α: **0.001** (strict) or **0.05** (looser).

### Old-school (used in the paper)

1. Gate by **Min height factor** (fraction of trace max).
2. Fit a Gaussian in **Gaussian fit width**.
3. Reject fits with **Max Gaussian σ** too large.
4. Ignore signal below **Minimum RT** (picker cutoff — **not** Null RT threshold).