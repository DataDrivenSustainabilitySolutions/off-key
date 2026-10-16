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
- [ ] Validate and commit the current product wordmarks.
- [ ] Normalize and preserve the merged-ti Aberratio presentation.
- [ ] Validate and commit the retained alternative and earlier studies.

## Validation

Check all original SVG hashes, black/white pairing, and the exact original rr
path. Use real Chrome to render the two sheets, verify mobile and desktop layout,
image loads, keyboard links and downloads, and inspect the saved screenshots.
Measure the alternative's lower-body ink to confirm b and ti both span 44 units.
Run the existing brand export check and whitespace checks. Before each commit,
confirm the staged path list contains only this branding work.
