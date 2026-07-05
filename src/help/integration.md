# Peak integration

This topic describes **integration windows on the chromatogram plot** — not the optional **`product_prominence.csv`** file from Library Analysis (see **Library pedigree** and **Export analysis bundle glossary**).

## Where to find it

In the **Chromatogram Visualizer**, open the **Peak analysis** panel and click **Show integration** (toggle to **Hide integration**). You must **Pick peaks** first.

Integration shading is a **visual aid** for inspecting individual traces. It does not run a separate analysis step.

## Height

**Height** is the count at the top of the peak (the apex).

## Area

**Area** is the sum of counts between the valleys on each side of the peak. This is the shaded region on the plot when integration is shown.

## Prominence

**Prominence** is peak height minus the higher of the two valleys beside the peak. It answers: “how much does this bump stand out from its shoulders?”

Prominence is also used as a **quality filter** during peak picking (min prominence) and, after pedigree RT assignment, in **`product_prominence.csv`** inside the analysis bundle.

## Percent area (%)

When several peaks are picked, **% area** is each peak’s share of the total integrated area. Non-overlapping peaks should sum to about 100%.

## Export from the peak panel

Use **Export CSV** in the peak panel to save RT, height, area, prominence, and p-value for each **displayed** peak on the current trace(s).

For library-wide product prominence at pedigree-validated RTs, run **Library Analysis → RT assignment** in **Pedigree** mode, then **Export analysis bundle…** — see **Export analysis bundle glossary** for `product_prominence.csv` columns.
