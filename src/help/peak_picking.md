# Peak picking

## What this does

**Pick peaks** finds bumps in your chromatogram that are large enough to be real signal, not random noise.

## Baseline (noise floor)

The program first estimates the **baseline** — the typical background count when no peak is present. It uses the same method as the Rust analysis engine: remove very high points, then take the median of what is left.

## Significance (α)

Each peak gets a **p-value**. Smaller p-value means stronger evidence the peak is real.

**α (alpha)** is your cutoff. A peak is kept when its p-value is below α. Common choices:

- **0.001** — strict (fewer peaks)
- **0.05** — looser (more peaks)

Lower α → fewer peaks called significant.

## What you see on the plot

- Colored circles on peak tops
- Orange shading between valleys (integration window)

## Tips

- Pick peaks on **one compound** and **one count channel** at a time for clearest results.
- If no peaks appear, try a larger α or check that the count channel has signal.
