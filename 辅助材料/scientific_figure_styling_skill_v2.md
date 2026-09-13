# Scientific Figure Styling & Argumentation Skill

## Purpose

Use this skill when generating figures for mathematical modeling competitions, scientific papers, technical reports, theses, or research presentations.

This is **not merely a plotting-style skill**. It is a **figure argumentation skill**: the figure must help the reader reach the intended scientific or modeling conclusion with less cognitive work.

> **A truly outstanding mathematical-modeling figure is not flashy. It should look as if it has already completed half of the analysis for the judge.**

The goal is to make an agent reliably produce figures that are:

- analytically useful,
- publication-quality,
- visually consistent,
- readable at final paper scale,
- honest about uncertainty and geometry,
- efficient in page space,
- reproducible from saved numerical outputs,
- and easy for a judge to interpret quickly.

Do **not** optimize for decorative effects. A beautiful figure that does not support an argument is still a weak figure.

---

# 1. Core Principle: Figure = Evidence + Interpretation

A paper figure should do more than display data. It should make the intended comparison, structure, uncertainty, trade-off, or conclusion visually obvious.

The agent should optimize for:

- **clarity** — what should the reader notice?
- **information density** — how much useful evidence is delivered per unit of page space?
- **visual hierarchy** — what is primary, secondary, and contextual?
- **consistency** — does the same object keep the same visual identity across the paper?
- **readability after scaling down** — does it still work at actual paper width?
- **evidence quality** — does the figure support a modeling claim rather than merely decorate it?
- **low visual noise** — are nonessential elements suppressed?

A good figure should reduce the amount of inference the judge has to perform manually.

Examples:

- Do not merely show an actual-value curve and a prediction curve. When statistically justified, also show the relevant uncertainty band, identify the test region, and highlight the largest or structurally important errors.
- Do not merely show an optimization convergence curve. Also make it clear what objective is converging, where the best solution lies, whether the result is stable across runs, and how the selected solution relates to constraints or Pareto trade-offs.
- Do not merely show a sensitivity heatmap. Mark the nominal parameter point, the feasible/stable region, and the region where conclusions change.

---

# 2. Figure Admission Gate — Decide Whether the Figure Deserves to Exist

Before plotting, create a short internal **Figure Brief**.

```text
Claim:
What single sentence should the reader be able to conclude from this figure?

Evidence:
What data/model output supports that claim?

Comparison / reference:
What baseline, benchmark, threshold, counterfactual, or competing method matters?

Uncertainty / robustness:
What uncertainty, repeated-run variability, sensitivity, or limitation must be visible?

Visual emphasis:
What should be visually dominant? What should be muted?

Caption takeaway:
What is the one-sentence interpretation that belongs in the caption or nearby text?
```

If the agent cannot fill these fields coherently, reconsider whether the figure belongs in the main paper.

### Main-text admission rule

A figure belongs in the main text when it materially supports at least one of the following:

- the model structure or mechanism;
- a central empirical/modeling result;
- a decisive comparison against a baseline;
- convergence or optimization behavior needed to trust the solution;
- uncertainty, error structure, sensitivity, or robustness;
- a spatial/network configuration that is hard to describe efficiently in prose;
- an important trade-off or feasible boundary;
- an explanation of *why* the selected solution is preferable.

### Move to appendix/supporting material when

- it is useful for reproducibility but not central to the argument;
- it repeats a result already summarized more efficiently in a table;
- it is a secondary diagnostic that does not affect the conclusion;
- it contains exhaustive parameter sweeps that would interrupt the narrative.

### Omit when

- it is visually attractive but analytically redundant;
- it merely re-plots a table without improving interpretation;
- it exists only because plotting it was easy;
- the paper never refers to the conclusion the figure supposedly demonstrates.

---

# 3. Figure Value Rubric

Score a candidate figure from 0–2 on each criterion.

```text
Claim clarity          0 1 2
Evidence sufficiency   0 1 2
Visual hierarchy       0 1 2
Robustness/uncertainty 0 1 2
Paper-scale readability 0 1 2
Non-redundancy         0 1 2
```

Suggested interpretation:

- **10–12**: strong main-text figure;
- **7–9**: keep if it fills a real narrative gap; otherwise appendix/supporting material;
- **4–6**: usually appendix or redesign;
- **0–3**: omit.

This rubric is not a formal competition scoring rule. It is an internal filter to stop the paper from becoming a gallery of technically valid but low-value plots.

---

# 4. Choose the Figure Type Before the Plotting Library

Do not select a library first and then force the problem into that library's favorite chart type.

Choose the **communication form** first, then the backend.

## Recommended backend policy

### Matplotlib + SciencePlots

Default for conventional scientific/statistical figures:

- line plots,
- scatter plots,
- bar/dot plots,
- heatmaps,
- box/violin plots,
- residual/diagnostic plots,
- uncertainty bands,
- Pareto plots,
- sensitivity plots,
- floorplans/layouts,
- custom multi-panel figures.

Use when deterministic static export and fine control matter.

### Graphviz

Prefer for:

- model pipelines,
- algorithm flowcharts,
- dependency graphs,
- state/decision structures,
- hierarchical method diagrams.

Do not manually place dozens of flowchart boxes in Matplotlib if Graphviz can produce cleaner automatic alignment.

### Plotly

Useful for:

- complex exploratory work before final export,
- Sankey diagrams,
- highly annotated trade-off plots,
- interactive inspection of dense results,
- some network/parallel-coordinate visualizations.

For the paper, export a static SVG/PDF/PNG rather than relying on interactivity. Avoid WebGL traces if a fully vector result is required, because some WebGL layers may be rasterized inside SVG/PDF.

### Altair / Vega-Lite

Useful for:

- faceted statistical graphics,
- small multiples,
- declarative layered charts,
- concise grammar-of-graphics workflows.

It can export SVG/PDF/PNG with the appropriate conversion dependency. Do not introduce it during a timed competition unless the team already knows the stack.

### NetworkX + Graphviz layout

Useful when the graph itself is part of the model and custom node/edge semantics are needed.

### Important

Do **not** switch away from Matplotlib merely to say that Matplotlib was not used. Library novelty contributes essentially nothing if the figure communicates worse.

---

# 5. Recommended Python Packages

For the Matplotlib path:

```bash
pip install SciencePlots cmcrameri adjustText
```

Optional:

```bash
pip install brokenaxes matplotlib-label-lines
```

For other backends when needed:

```bash
pip install graphviz
pip install "plotly[kaleido]"
pip install altair vl-convert-python
```

Primary roles:

- `SciencePlots`: publication-oriented Matplotlib style presets;
- `cmcrameri`: perceptually designed scientific colormaps;
- `adjustText`: automatic label-collision reduction;
- `graphviz`: clean algorithm/model diagrams;
- `plotly + kaleido`: exploratory plotting plus static SVG/PDF/PNG export;
- `altair + vl-convert`: declarative statistical graphics and static export.

Use optional packages only when they genuinely improve communication.

---

# 6. Default Matplotlib Initialization

Use this as the default plotting setup for conventional scientific figures unless the task requires another style.

```python
import matplotlib.pyplot as plt
import matplotlib as mpl
import scienceplots
import cmcrameri.cm as cmc

plt.style.use(["science", "no-latex", "muted"])

mpl.rcParams.update({
    "figure.dpi": 150,
    "savefig.dpi": 600,

    "font.size": 9,
    "axes.titlesize": 9,
    "axes.labelsize": 9,
    "legend.fontsize": 8,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,

    "axes.linewidth": 0.8,
    "lines.linewidth": 1.4,
    "lines.markersize": 4,

    "xtick.major.width": 0.7,
    "ytick.major.width": 0.7,

    "axes.spines.top": False,
    "axes.spines.right": False,

    "legend.frameon": False,

    # Prefer embeddable TrueType text in PDF/PS.
    "pdf.fonttype": 42,
    "ps.fonttype": 42,

    # Editable SVG text. For maximum portability, verify the target machine
    # has the required font; otherwise consider paths for the final asset.
    "svg.fonttype": "none",

    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.04,
})
```

### Style policy

Default paper style:

```python
plt.style.use(["science", "no-latex", "muted"])
```

Presentation-style figures, when explicitly needed:

```python
plt.style.use(["science", "no-latex", "bright"])
```

Do not switch styles randomly within one paper.

Do not use a journal-specific preset merely because its name sounds prestigious. The style must fit the actual paper and remain consistent.

---

# 7. Global Visual Language

## Background

Use a white background.

Avoid:

- dark backgrounds,
- gradients,
- shadows,
- glossy effects,
- decorative cards,
- pseudo-3D effects,
- dashboard styling unless the deliverable is actually a dashboard.

## Semantic color mapping

The same object must keep the same color across the whole paper.

Example:

```python
SEMANTIC_COLORS = {
    "proposed": "#0072B2",
    "baseline": "#777777",
    "alternative": "#009E73",
    "warning": "#D55E00",
    "uncertainty": "#56B4E9",
}
```

Recommended categorical palette when several clearly separated categories are needed: Okabe–Ito-style colors.

```python
OKABE_ITO = [
    "#0072B2",  # blue
    "#E69F00",  # orange
    "#009E73",  # bluish green
    "#D55E00",  # vermillion
    "#CC79A7",  # reddish purple
    "#56B4E9",  # sky blue
]
```

Use yellow (`#F0E442`) cautiously on a white background because contrast can be weak.

### Color rule

Usually use no more than 3–4 visually dominant colors in one figure, plus gray/context tones.

Color should encode meaning, not decoration.

Do not rely on color alone. When a distinction is important, reinforce it with at least one of:

- line style,
- marker shape,
- direct label,
- fill/hatching,
- lightness difference.

## Forbidden / discouraged colormaps

Do not use:

```python
"jet"
"rainbow"
"gist_rainbow"
```

unless the scientific semantics explicitly require a cyclic/rainbow-like encoding and a defensible alternative is unavailable.

## Scientific colormap policy

Select a colormap by data semantics, not by habit.

For a one-direction continuous scalar field, use a perceptually ordered sequential map, for example:

```python
cmap = cmc.batlow
```

For signed deviation around a meaningful zero/reference value:

```python
cmap = cmc.vik
```

For another monotonic sequential quantity:

```python
cmap = cmc.lajolla
```

For diverging data, center the map at the meaningful reference value whenever possible.

---

# 8. Visual Hierarchy: Tell the Reader Where to Look

A figure should not give equal visual weight to every element.

Recommended hierarchy:

1. **Primary conclusion / proposed solution** — strongest visual weight.
2. **Baseline / reference / threshold** — visible but quieter.
3. **Context / feasible samples / secondary models** — muted.
4. **Grid / axes / decorations** — weakest.

Example for optimization:

- all feasible solutions: light gray, small markers;
- Pareto front: clear line + markers;
- selected operating point: distinct highlight + annotation;
- dominated points: deliberately de-emphasized.

Example for model comparison:

- proposed/final model: strong semantic color;
- baseline: gray;
- discarded alternatives: muted colors or moved to a table.

Do not create a twelve-color model zoo plot unless the comparison itself is the scientific question.

---

# 9. Uncertainty and Robustness Must Be Honest

Do **not** automatically add a “95% confidence band” because it looks scientific.

Only visualize uncertainty that is actually defined and supported by the modeling procedure.

Possible quantities include:

- confidence interval for an estimated parameter/statistic;
- prediction interval for a future observation;
- bootstrap interval;
- posterior credible interval;
- standard deviation / interquartile range across repeated runs;
- sensitivity range under parameter perturbation;
- scenario envelope.

The caption or legend should identify what the band/whisker means.

Bad:

```text
Shaded region: 95% interval
```

Better:

```text
Shaded region: 95% bootstrap confidence interval of the median prediction error
```

or

```text
Band: interquartile range across 30 independent optimization runs
```

If uncertainty cannot be estimated defensibly, do not fabricate a band. Show deterministic results honestly and discuss the limitation in text.

---

# 10. Axes, Ticks, Grid, Legends, and Text

## Axes

Default behavior:

- remove top and right spines unless enclosure is meaningful;
- use thin axis lines;
- use meaningful units in axis labels;
- avoid repeating units in every tick label;
- use log scale only when it clarifies multiplicative behavior or broad dynamic range;
- never use axis limits that visually exaggerate differences without a defensible reason.

## Tick density

Prefer roughly 4–7 meaningful major ticks per axis when possible.

Avoid dense minor ticks unless they improve quantitative reading.

## Grid

Do not enable a grid by default.

If used, keep it weak:

```python
ax.grid(True, which="major", alpha=0.18, linewidth=0.6)
```

## Legends

Prefer direct labeling when practical.

If a legend is needed:

- no heavy frame;
- keep it compact;
- place it away from dense data;
- avoid repeating obvious labels;
- keep ordering meaningful and consistent across figures.

## Titles

Do not put large presentation-style titles inside paper figures.

Prefer:

- concise panel titles;
- `(a)`, `(b)`, `(c)` labels;
- detailed explanation in the caption.

## Annotations

Annotate only values or events that change interpretation:

- selected optimum;
- threshold crossing;
- changepoint;
- largest meaningful error;
- knee point on Pareto front;
- critical parameter region;
- baseline reference;
- constraint boundary.

Do not label every point simply because labels are available.

If labels overlap, use `adjustText` or redesign the labeling strategy.

---

# 11. Figure Size Rules

Choose size based on final use, not monitor appearance.

Typical starting points:

```python
# Compact / single-column-like
fig, ax = plt.subplots(figsize=(3.4, 2.6))

# Medium paper figure
fig, ax = plt.subplots(figsize=(5.5, 3.6))

# Full-width figure
fig, ax = plt.subplots(figsize=(7.0, 4.2))
```

Do not create a huge canvas and shrink it dramatically afterward.

The agent must judge readability at the **actual intended paper width**.

---

# 12. Multi-Panel Figures

Use multi-panel figures when the panels jointly answer one larger question.

Recommended:

```python
fig, axes = plt.subplots(
    1, 3,
    figsize=(7.2, 2.5),
    constrained_layout=True
)
```

Panel labels:

```python
for label, ax in zip(["(a)", "(b)", "(c)"], axes):
    ax.text(
        -0.12, 1.05, label,
        transform=ax.transAxes,
        fontsize=9,
        fontweight="bold",
        va="top"
    )
```

Keep:

- aligned margins;
- matching font sizes;
- matching line widths;
- matching color semantics;
- comparable scales when comparison requires it.

Do not combine unrelated plots merely to save figure numbers.

A multi-panel figure should function as a small argument, not a collage.

---

# 13. Figure Patterns for Mathematical Modeling Competitions

## 13.1 Prediction / Forecasting

Weak version:

- actual vs predicted curves only.

Stronger version when supported:

- actual values;
- predictions;
- explicit train/validation/test region distinction if relevant;
- valid uncertainty band;
- annotation of structurally important errors;
- residual/error panel or separate diagnostic figure;
- metric shown only if it aids interpretation and is not redundant with the surrounding text.

Do not place five metrics in a decorative inset if they are already in a comparison table.

For classification, consider:

- precision–recall curves when class imbalance makes ROC less informative;
- calibration plots when predicted probabilities are used operationally;
- confusion matrices when error types matter;
- threshold-performance curves when the threshold is a decision variable.

## 13.2 Optimization

Useful evidence chain:

```text
search / convergence
        ↓
feasibility or candidate solution space
        ↓
Pareto / objective trade-off
        ↓
selected solution
        ↓
sensitivity / repeated-run robustness
```

Do not automatically include every stage; include the stages needed to make the selected solution credible.

For stochastic algorithms, one convergence curve from the best run is often insufficient. When possible, show repeated-run variability or report it numerically.

## 13.3 Evaluation / Ranking

Prefer:

- ordered dot plots;
- horizontal bars;
- contribution plots;
- rank-change or sensitivity plots;
- compact heatmaps.

Use radar charts cautiously. They are visually attractive but make precise comparison difficult, especially with many methods or dimensions.

## 13.4 Sensitivity / Robustness

High-value patterns:

- parameter–objective response curves;
- tornado plots;
- two-parameter heatmaps;
- relative-change plots;
- scenario comparison;
- repeated-run distribution;
- stability region maps.

Mark the nominal parameter point and the region where the conclusion changes.

The point is not merely to show that parameters were perturbed. The figure should reveal **whether the model conclusion survives the perturbation**.

## 13.5 Spatial Problems / Maps / Layout

Encode the result directly in space whenever geography or geometry is central.

For floorplan/packing/placement:

- preserve equal aspect ratio;
- preserve geometry truthfully;
- use light fills and thin borders;
- label only modules large enough to read;
- do not cosmetically distort a long/narrow solution to make it look nicer.

## 13.6 Network / Routing / Dependency Problems

Use node size, edge width, color, or line style only when each has a defined meaning.

Avoid a “hairball” network. If the full graph is unreadable, show:

- the selected route/subgraph;
- community-level aggregation;
- high-centrality nodes;
- before/after comparison;
- a separate quantitative summary.

## 13.7 Clustering / Dimensionality Reduction

If using PCA/t-SNE/UMAP for visualization, clearly state that the 2D layout is a projection/embedding.

Do not imply that apparent 2D separation proves equally strong separation in the original feature space.

Pair projection plots with quantitative clustering evidence when that evidence matters.

---

# 14. Line Plots

Use:

- moderate line width;
- small markers only when needed;
- restrained marker frequency;
- direct highlighting of important points.

Example:

```python
fig, ax = plt.subplots(figsize=(5.5, 3.4))

ax.plot(
    x,
    y,
    marker="o",
    markevery=max(1, len(x)//12),
    linewidth=1.4,
    markersize=4,
    label="Method A"
)

ax.set_xlabel("Iteration")
ax.set_ylabel("Objective value")
ax.legend()

fig.savefig("convergence.pdf")
```

For convergence curves:

- use log scale if it reveals behavior more clearly;
- annotate the final/best value when useful;
- consider repeated-run envelopes for stochastic optimizers;
- avoid plotting every raw noisy point if it becomes visual fur.

---

# 15. Scatter Plots

For small datasets:

```python
ax.scatter(x, y, s=28, alpha=0.85)
```

For large datasets:

```python
ax.scatter(x, y, s=8, alpha=0.35, rasterized=True)
```

For dense scatter plots, consider:

- hexbin;
- 2D histogram;
- density contours;
- transparent points;
- sampling only for display while computing statistics on the full dataset.

Do not outline every point with a thick black edge unless the dataset is very small and the outline adds meaning.

---

# 16. Bar / Dot Charts

Prefer simple bars or ordered dot plots.

Avoid:

- 3D bars;
- gradients;
- heavy borders;
- shadows;
- more category colors than necessary.

Example:

```python
bars = ax.bar(labels, values, width=0.62)

for bar, value in zip(bars, values):
    ax.text(
        bar.get_x() + bar.get_width()/2,
        bar.get_height(),
        f"{value:.2f}",
        ha="center",
        va="bottom",
        fontsize=7
    )
```

If comparing many methods, a dot plot or horizontal bar chart is often easier to scan than a forest of vertical bars.

---

# 17. Heatmaps and Sensitivity Maps

Default sequential example:

```python
im = ax.imshow(
    Z,
    cmap=cmc.batlow,
    aspect="auto",
    origin="lower"
)
```

Add a labeled colorbar:

```python
cbar = fig.colorbar(im, ax=ax)
cbar.set_label("Hit rate (%)")
```

For signed deviations around zero:

```python
im = ax.imshow(
    Z,
    cmap=cmc.vik,
    vmin=-vmax,
    vmax=vmax
)
```

Avoid writing a number in every heatmap cell unless the matrix is small and the numbers materially aid interpretation.

For sensitivity maps, consider marking:

- nominal parameter values;
- feasible/stable regions;
- threshold contours;
- the selected operating point.

---

# 18. Pareto Front Figures

For multi-objective modeling:

- plot all feasible solutions softly;
- emphasize non-dominated points;
- annotate only key candidates;
- mark the selected compromise solution;
- if a knee point is used, explain the selection criterion;
- avoid equal emphasis for every point.

Example pattern:

```python
ax.scatter(
    all_x,
    all_y,
    s=12,
    alpha=0.20,
    label="Feasible solutions"
)

ax.plot(
    pareto_x,
    pareto_y,
    marker="o",
    linewidth=1.6,
    markersize=4,
    label="Pareto front"
)

ax.scatter(
    selected_x,
    selected_y,
    s=45,
    zorder=5,
    label="Selected solution"
)
```

A Pareto figure should help the reader understand **why this solution was selected**, not only where the front lies.

---

# 19. Floorplan / Layout Figures

For VLSI, packing, placement, zoning, facility layout, or spatial optimization:

Use rectangles with:

- light fills;
- thin borders;
- equal axis scaling;
- visible but non-dominant labels;
- minimal empty margins.

Example:

```python
from matplotlib.patches import Rectangle

fig, ax = plt.subplots(figsize=(5.2, 5.0))

for block in blocks:
    rect = Rectangle(
        (block.x, block.y),
        block.w,
        block.h,
        linewidth=0.5,
        edgecolor="0.45",
        facecolor=block.color,
        alpha=0.72
    )
    ax.add_patch(rect)

    if block.w * block.h > label_area_threshold:
        ax.text(
            block.x + block.w / 2,
            block.y + block.h / 2,
            block.name,
            ha="center",
            va="center",
            fontsize=5.5
        )

ax.set_aspect("equal")
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.set_xlabel("x")
ax.set_ylabel("y")
```

For dense floorplans:

- label only selected/important modules;
- move summary metrics outside the main geometry;
- keep orientation legends small;
- preserve the true aspect ratio.

Do not distort geometry for aesthetics.

---

# 20. Flowcharts and Method Diagrams

For technical papers, default to:

- white background;
- thin gray/black lines;
- simple boxes;
- limited pastel accents;
- minimal or no icons;
- consistent alignment;
- explicit direction of information flow.

Prefer Graphviz when the diagram is primarily a directed graph/pipeline.

Example Graphviz pattern:

```python
from graphviz import Digraph

G = Digraph("model_pipeline", format="svg")
G.attr(rankdir="LR", splines="ortho")
G.attr("node", shape="box", style="rounded", fontsize="10")

G.node("data", "Data preprocessing")
G.node("model", "Model / optimization")
G.node("validate", "Validation & sensitivity")
G.node("decision", "Decision / recommendation")

G.edge("data", "model")
G.edge("model", "validate")
G.edge("validate", "decision")

G.render("model_pipeline", cleanup=True)
```

Do not create a product-dashboard infographic unless the user explicitly requests one.

A method diagram should make the modeling logic easier to reconstruct, not merely look polished.

---

# 21. Captions Are Part of the Figure

A weak caption merely names the picture.

Weak:

```text
Figure 7. Sensitivity analysis.
```

Better:

```text
Figure 7. Sensitivity of objective value and constraint violation to λ and μ; the marker denotes the nominal parameter pair and the contour indicates the feasibility boundary.
```

When relevant, captions should identify:

- what is plotted;
- units;
- data split / scenario;
- uncertainty definition;
- number of independent runs or samples;
- baseline/reference;
- the key interpretation.

Do not bury an essential decoding rule only in the surrounding prose.

The figure and caption together should be interpretable with minimal backtracking.

---

# 22. Paper-Level Figure System

Do not design figures independently. Design a **figure system** for the whole paper.

A strong modeling paper often needs some subset of the following evidence chain:

```text
Problem / model overview
        ↓
Data structure or key phenomenon
        ↓
Core model result
        ↓
Comparison / diagnostics
        ↓
Robustness / sensitivity
        ↓
Decision / interpretation
```

Not every paper needs every stage.

The purpose is to make the paper visually narrate the modeling argument.

### Suggested role allocation

- **Overview figure**: only if model structure is nontrivial and the diagram saves explanation.
- **Core result figure**: the most important quantitative result.
- **Diagnostic/comparison figure**: why the model is credible relative to alternatives or baselines.
- **Robustness figure**: whether the conclusion survives reasonable perturbations.
- **Decision/interpretation figure**: why the chosen solution is useful or preferable.

Do not spend main-text page space showing every exploratory plot produced during modeling.

---

# 23. Model-Zoo Warning

More models do not automatically produce stronger evidence.

If many models were tried:

- use a compact table for broad metric comparison;
- visualize only the comparisons that teach the reader something;
- highlight the final model and a meaningful baseline;
- if accuracy differences are tiny, consider plotting accuracy vs complexity/runtime/interpretability instead of pretending the tiny difference is profound;
- remove failed/irrelevant models from the main narrative unless they support an important methodological point.

A paper should look like a reasoned modeling process, not a zoological census.

---

# 24. Result-to-Figure Examples

## Prediction example

Instead of:

```text
Actual vs predicted
```

prefer, when justified:

```text
Actual values
+ predicted values
+ test-region indication
+ uncertainty or repeated-run band
+ key error annotation
+ separate residual diagnostic
```

## Optimization example

Instead of:

```text
One convergence curve
```

consider:

```text
Convergence behavior
+ candidate/feasible space
+ Pareto trade-off
+ selected point
+ sensitivity or repeated-run stability
```

## Ranking/evaluation example

Instead of:

```text
A decorative radar chart with 12 indicators
```

consider:

```text
Ordered score plot
+ contribution/weight view
+ ranking stability under weight perturbation
```

The final choice depends on the question. Do not mechanically produce every listed component.

---

# 25. Export Strategy

## Vector-first, not vector-at-all-costs

For most scientific line/text/shape content, prefer a vector master:

```python
fig.savefig("figure.pdf", bbox_inches="tight")
fig.savefig("figure.svg", bbox_inches="tight")
```

Also generate PNG when useful for preview/compatibility:

```python
fig.savefig("figure.png", dpi=600, bbox_inches="tight")
```

However, do **not** force millions of scatter points or large raster fields into pure vector geometry.

For heavy artists:

```python
ax.scatter(x, y, rasterized=True)
```

This keeps text, axes, and annotations vector while rasterizing the expensive data layer.

### Practical target

- Word paper: SVG is often convenient; verify font rendering on the final machine.
- LaTeX paper: PDF is often the safest vector choice.
- PNG: preview, compatibility, or genuinely raster data.
- Dense heatmaps/images: raster layer is appropriate; keep labels/axes vector where possible.

### Font portability

Matplotlib can emit editable SVG text with:

```python
mpl.rcParams["svg.fonttype"] = "none"
```

but editable text depends on the viewing system having the expected fonts.

For a final asset that must look identical everywhere, converting SVG text to paths can improve portability at the cost of editability and sometimes file size.

Always inspect the actual exported file in the target document workflow.

---

# 26. CUMCM Competition Constraints

For the 2026 CUMCM format, design choices must respect the paper-level constraints:

- main text begins after the abstract page and is limited to **30 pages**;
- electronic paper is submitted as a single PDF or Word file and must be **no larger than 20 MB**;
- source code and supporting materials must correspond to the paper results;
- the official format does not otherwise impose a universal font/color style, so consistency and readability are the team's responsibility.

Implications for figures:

- every main-text figure should earn its page space;
- avoid huge 600-dpi raster images when vector or selective rasterization is smaller;
- avoid giant SVG files containing hundreds of thousands of vector points;
- keep the final document under the size limit;
- ensure figure-generation code and reported results are reproducible from the submitted support material.

---

# 27. Agent Workflow

When asked to produce a paper figure, follow this workflow.

## Step A — Define the communication goal

Write the Figure Brief.

Determine whether the figure is supposed to show:

- convergence;
- comparison;
- sensitivity;
- distribution;
- correlation;
- prediction/forecasting;
- uncertainty;
- spatial arrangement;
- Pareto trade-off;
- feasibility boundary;
- model structure;
- robustness;
- decision consequence.

Do not choose a chart merely because it is easy to code.

## Step B — Decide whether a figure is the best medium

Ask whether the result is better communicated by:

- prose;
- a small table;
- a figure;
- a multi-panel figure;
- appendix/supporting material.

## Step C — Choose the simplest effective figure type

Prefer:

- line chart for evolution;
- dot/bar chart for categorical comparison;
- heatmap for matrix-like sensitivity;
- scatter for relationships;
- Pareto plot for trade-offs;
- rectangle layout for packing/placement;
- violin/box plot for distributions;
- Graphviz for method flow;
- map for geographic structure.

Avoid mixing chart types unless it improves interpretation.

## Step D — Choose the backend

Use the backend policy in Section 4.

## Step E — Render a first draft

Use the paper's semantic color system and consistent typography.

## Step F — Visually inspect the rendered output

Inspect the rendered PNG/SVG/PDF whenever image inspection is available.

Check:

- text collision;
- clipped labels;
- legend overlap;
- excessive whitespace;
- dense ticks;
- poor contrast;
- visually unbalanced panels;
- inconsistent colors;
- unreadable small text;
- distorted aspect ratio;
- whether the intended conclusion is visually obvious;
- whether the figure still works in grayscale;
- whether the plot remains readable at final paper width.

## Step G — Revise automatically

Do not stop at the first technically valid rendering.

Modify code based on inspection.

## Step H — Export final assets

Export the appropriate vector/raster combination and verify the final document rendering.

---

# 28. Mandatory Final QA Checklist

Before delivery, verify:

```text
[ ] The figure supports a specific claim.
[ ] The reader can identify the intended takeaway quickly.
[ ] The figure is not redundant with a nearby table/text block.
[ ] Baseline/reference/threshold is visible when relevant.
[ ] Uncertainty is shown when justified and correctly labeled.
[ ] No fabricated or ambiguous “95% interval”.
[ ] No overlapping text.
[ ] No clipped labels or annotations.
[ ] Legend does not hide important data.
[ ] No unnecessary giant title.
[ ] No meaningless decorative color.
[ ] No jet/rainbow colormap without justification.
[ ] Color is not the sole carrier of an important distinction.
[ ] Top/right spines are removed unless justified.
[ ] Tick density is reasonable.
[ ] Axes/geometry are not distorted to exaggerate results.
[ ] Figure is readable at actual paper scale.
[ ] Multi-panel alignment is consistent.
[ ] Semantic colors match the rest of the paper.
[ ] Important values/regions are visually identifiable.
[ ] Caption explains necessary decoding and uncertainty semantics.
[ ] Heavy data layers are rasterized when vector export would be pathological.
[ ] PDF/SVG/PNG export has been checked in the target document workflow.
[ ] File size is reasonable for the final submission.
[ ] No low-value dashboard-like decoration.
```

---

# 29. Strong Agent Instruction

When generating paper figures, obey the following instruction:

```text
Create a publication-quality scientific figure that functions as evidence, not a default plotting output.

The figure should make the intended modeling conclusion easier to see. A strong mathematical-modeling figure is not flashy; it should look as if it has already completed half of the analysis for the judge.

Before plotting, define:
- the claim the figure must support;
- the evidence shown;
- the relevant baseline/reference;
- the uncertainty or robustness information, if justified;
- what should be visually emphasized;
- the one-sentence takeaway.

If the figure does not materially support the paper's argument, move it to supporting material or omit it.

Choose the figure type before the plotting library.

Backend policy:
- Matplotlib + SciencePlots for conventional scientific/statistical plots and custom layouts;
- Graphviz for technical flowcharts/model pipelines;
- Plotly for complex exploratory/annotated plots or Sankey-style graphics, then export static assets;
- Altair for declarative/faceted statistical graphics when the environment already supports it.

Visual requirements:
- white background;
- stable semantic colors across the whole paper;
- small color palette;
- thin axes/borders;
- no unnecessary grid;
- no decorative 3D, shadows, gradients, glossy effects, or dashboard cards;
- no jet/rainbow colormap without scientific justification;
- use perceptually appropriate sequential/diverging colormaps;
- do not rely on color alone for important distinctions;
- compact unobtrusive legends or direct labels;
- avoid oversized titles inside the figure;
- use (a), (b), (c) labels for coherent multi-panel figures;
- maintain consistent font size, line width, and marker size;
- annotate only values/regions that change interpretation;
- preserve true geometry and scale;
- never manipulate axes to exaggerate a result;
- ensure readability after shrinking to final paper size.

Uncertainty requirements:
- show uncertainty only when it is actually defined by the model/data;
- clearly identify whether it is a confidence interval, prediction interval, bootstrap interval, credible interval, repeated-run variability, sensitivity range, or scenario envelope;
- never fabricate a generic 95% band for visual effect.

Competition-paper requirements:
- prioritize figures that prove the central result, comparison, robustness, or decision logic;
- do not create a model-zoo gallery;
- use tables for exhaustive model metrics when a plot adds little;
- use vector output for text/axes/lines but rasterize very heavy artists when necessary;
- keep the final paper readable and within the submission file-size constraint.

After the first render, visually inspect and revise if there is:
- text overlap;
- excessive whitespace;
- poor legend placement;
- dense ticks;
- inconsistent colors;
- weak hierarchy;
- unreadable labels;
- poor panel alignment;
- ambiguous uncertainty;
- misleading scale;
- or no obvious visual takeaway.

Do not deliver the first technically valid render blindly.

Export the appropriate combination of PDF/SVG/PNG and verify the final document rendering.
```

---

# 30. Anti-Patterns

Do not do any of these unless explicitly justified:

```text
Default Matplotlib styling with no deliberate hierarchy
A figure with no clear analytical claim
Rainbow / jet colormaps
3D bar charts
Decorative 3D surfaces for essentially 2D relationships
Pie charts with many categories
Huge legends
Huge in-figure titles
Thick black outlines around every data point
Heavy grid lines
Gradient backgrounds
Drop shadows
Rounded-card dashboard design
Tiny unreadable text
Putting every numeric value directly on the plot
Too many simultaneous colors
Changing the same method's color between figures
A generic “95% confidence band” with no statistical definition
Showing only the best stochastic optimization run
Plotting twelve models just because twelve models were trained
Using a low-resolution PNG as the primary paper asset
Forcing dense scatter/heatmap data into a gigantic pure-vector file
Distorting map/layout/floorplan geometry to improve aesthetics
Using t-SNE/UMAP separation as if it proved separation in the original space
```

---

# 31. Competition Mode

During a time-limited mathematical modeling competition:

1. Prioritize correctness of model outputs.
2. Save numerical outputs separately from plotting code (`csv`, `parquet`, `json`, `npz`, etc.).
3. Generate figures from saved outputs instead of rerunning expensive models only to change styling.
4. Establish one global figure theme early.
5. Prioritize a small number of high-value figures:
   - central result;
   - decisive comparison/diagnostic;
   - robustness/sensitivity;
   - selected solution/decision logic.
6. Use a compact table for exhaustive secondary model comparisons.
7. Render important figures automatically.
8. Visually inspect the figures that will enter the main text.
9. Fix the most visible problems first:
   - unreadable fonts;
   - excessive whitespace;
   - legend placement;
   - color inconsistency;
   - panel alignment;
   - misleading axis scaling;
   - ambiguous uncertainty;
   - pathological raster/vector size.
10. Export and verify final assets in the actual Word/LaTeX/PDF workflow.

A good scientific figure usually comes from a stable visual system and a clear analytical purpose, not artisanal RGB tuning at 4 a.m.

---

# 32. Suggested Repository Structure

For a competition repository:

```text
project/
├─ data/
├─ results/
│  ├─ metrics.csv
│  ├─ predictions.csv
│  ├─ sensitivity.npz
│  └─ optimization_runs.csv
├─ src/
│  ├─ model.py
│  ├─ optimize.py
│  └─ ...
├─ figures/
│  ├─ style.py
│  ├─ make_figures.py
│  ├─ fig01_pipeline.svg
│  ├─ fig02_core_result.pdf
│  └─ ...
└─ paper/
```

Recommended design:

- `style.py`: all semantic colors, font sizes, line widths, export helpers;
- `make_figures.py`: deterministic generation of paper figures from `results/`;
- avoid burying critical plotting logic inside notebooks that cannot be reproduced cleanly.

---

# 33. Maintenance Notes / Evidence Basis

These are maintainer-facing notes, not requirements that must be reproduced inside every paper.

- 2026 CUMCM format: main text no more than 30 pages; electronic paper no more than 20 MB; supporting materials must correspond to paper results.  
  https://www.mcm.edu.cn/html_cn/node/4cd596519c9eb9fbd866398f6df0caa3.html

- Matplotlib font/export behavior, including PDF font embedding and SVG `fonttype`:  
  https://matplotlib.org/stable/users/explain/text/fonts.html

- SciencePlots provides publication-oriented Matplotlib styles and color cycles:  
  https://github.com/garrettj403/SciencePlots

- Plotly static export uses Kaleido; current Kaleido requires compatible Chrome/Chromium and supports static formats including SVG/PDF/PNG:  
  https://plotly.com/python/static-image-generation-changes/

- Altair supports SVG/PDF/PNG export through its current conversion dependencies:  
  https://altair-viz.github.io/user_guide/saving_charts.html

- Scientific figure literature emphasizes interpretability, color-vision accessibility, appropriate uncertainty displays, and direct/clear annotation rather than decorative complexity.  
  https://pmc.ncbi.nlm.nih.gov/articles/PMC7040535/  
  https://pmc.ncbi.nlm.nih.gov/articles/PMC8041175/  
  https://www.nature.com/articles/s41562-026-02466-9
