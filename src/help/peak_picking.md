# Peak picking

## Where

- **Chromatogram Visualizer → Peak analysis** — **Pick peaks** on selected compounds.
- **Library Analysis → RT assignment** — same algorithms for library-wide RT assignment.

## Algorithms

Choose **Modern** or **Old-school**. Only the active column’s parameters apply.

### Modern (default)

1. Estimate baseline μ and σ.
2. Find local maxima above baseline.
3. Keep peaks where height and area p-values are both < **α/2**.

Typical α: **0.001** (strict) or **0.05** (looser).

### Old-school (paper Methods)

1. Gate by **Min height factor** (fraction of trace max).
2. Fit a Gaussian in **Gaussian fit width**.
3. Reject fits with **Max Gaussian σ** too large.
4. Ignore signal below **Minimum RT** (picker cutoff — **not** Null RT threshold).

Modern was added after the accompanying paper.

## Quality filters (both)

- **Min prominence** — height above the higher adjacent valley.
- **Min % area** — share of total detected area.

Set either to **0** to disable. Peaks below cutoffs are hidden from the plot/table but still detected. Same filters apply to Library Analysis when set on the RT / QC sidebars.

## Plot & export

Markers on peak tops; optional integration shading (**Show integration** in the peak panel shades each peak's area between its flanking valleys). **Export CSV** in the peak panel saves displayed peaks. Library-wide tables: **Export RTs…** / **Export analysis bundle…**.

## Tips

- Prefer one compound and one count channel when inspecting.
- No modern peaks → raise α or check the channel has signal.
- No old-school peaks → check **Minimum RT** and **Min height factor** vs your time unit and scale.
