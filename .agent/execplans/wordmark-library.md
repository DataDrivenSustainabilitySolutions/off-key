# Preserve the selected wordmark directions

## Objective

Keep Aberration as the product name and preserve both wordmark directions in
scoped repository commits. The current direction is the original lowercase
aligned stack and single line, with separate t and i. The retained Aberratio
direction uses the merged, flush-stem ti whose lower body matches b.

The referenced .agent/PLANS.md is absent; this file records the plan directly.

## Approach

- Preserve the SVG geometry and existing studies. Remove the capital-A variant
  from the current comparison only.
- Give the two selected presentation sheets one shared stylesheet and the same
  light/dark specimen layout. Keep their previews beside the SVG sources in the
  repository rather than only in ignored temporary output.
- Document the current product selection and the retained alternative.
- Commit the current Aberration set first, then the alternative and earlier
  experiments. Stage exact paths, excluding concurrent pipeline work.

## Progress

- [x] Inspect repository state, source assets, preview pages, and commit hooks.
- [x] Normalize the current Aberration presentation and save its previews.
- [x] Validate and commit the current product wordmarks (d19b41d).
- [x] Normalize and preserve the merged-ti Aberratio presentation.
- [x] Validate the retained alternative and prepare its separate scoped commit.

## Results

Both selected sheets share one stylesheet and save desktop/mobile PNGs under
assets/brand/experiments/previews. The current comparison contains only the
original lowercase Aberration stack and single line. The alternative presents
the merged, body-matched ti first and preserves its earlier compound below.

Real Chrome checks pass for source consistency, both colour treatments, image
loading, keyboard focus, downloads, and 320/390/768/1280px layouts. Pixel sampling
across the lower stems confirms b and the flush-stem ti are both 44 units wide;
the earlier compound is 34 units. All 18 original SVG files match their initial
SHA-256 hashes. Local HTML references, brand exports, script syntax, whitespace,
and preview file-size checks pass. The current product commit's repository hooks
also pass.

The two commits are restricted to brand assets and this plan. Existing pipeline
and deployment edits are excluded.

## Validation

Check all original SVG hashes, black/white pairing, and the exact original rr
path. Use real Chrome to render the two sheets, verify mobile and desktop layout,
image loads, keyboard links and downloads, and inspect the saved screenshots.
Measure the alternative's lower-body ink to confirm b and ti both span 44 units.
Run the existing brand export check and whitespace checks. Before each commit,
confirm the staged path list contains only this branding work.
