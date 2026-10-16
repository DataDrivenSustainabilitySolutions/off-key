# Publish the selected wordmark library

## Objective

Keep Aberration as the product name. Preserve its original lowercase aligned
stack and single line, with separate t and i, plus the retained Aberratio
alternative with the merged, flush-stem ti whose lower body matches b.

Promote these selected SVGs beside the main logo and favicon in assets/brand,
retain their desktop/mobile PNG presentations, and remove the rejected designs
from the current checkout. Earlier designs remain in Git history.

The referenced .agent/PLANS.md is absent; this file records the plan directly.

## Approach

- Move the six selected SVGs into assets/brand with consistent wordmark names.
  Preserve the source bytes, including all letter outlines and spacing.
- Keep the two selected HTML specimen sheets, their shared stylesheet, renderer,
  and four presentation PNGs together under assets/brand/previews.
- Remove rejected capital-A, spacing, ascender, paired-letter, and earlier-ti
  sources and their obsolete comparison pages, as requested by the user.
- Consolidate the usage notes and asset links in assets/brand/README.md.
- Validate the final structure in real Chrome, then commit and update the
  existing branding PR without changing the shared pipeline checkout.

## Progress

- [x] Preserve the original Aberration direction and merged-ti Aberratio option.
- [x] Normalize both selected sheets and omit earlier compounds and detail plots.
- [x] Isolate the branding commits on codex/aberration-wordmarks and open PR #311.
- [x] Promote selected SVGs, retain presentation sources/PNGs, and remove rejects.
- [x] Verify all new paths, unchanged SVG bytes, previews, and brand exports.
- [x] Prepare the scoped cleanup commit and updated description for PR #311.

## Validation

Compare all six promoted SVGs and the four existing standalone logo/favicon
sources against their pre-move SHA-256 hashes. Check black/white pairing and the
exact original rr path. Use real Chrome to render both sheets, verify image
loads, keyboard links, downloads, and 320/390/768/1280px layouts. Measure the
alternative's lower-body ink to confirm b and ti both span 44 units. Inspect the
saved screenshots, resolve local asset links, and run the existing brand export
and whitespace checks. Confirm the commit contains only brand assets and this
plan, and that no rejected designs remain in the current asset tree.

## Results

All six selected SVGs and the four standalone logo/favicon sources match their
pre-move SHA-256 hashes. Only the selected SVGs remain in assets/brand, and the
rejected files and obsolete comparison pages are removed. The four desktop/mobile
PNG presentations and their HTML/CSS sources are retained under previews.

Real Chrome checks pass for both pages at 320, 390, 768, and 1280 pixels, including
image loading, keyboard focus, and all six SVG downloads. Pixel measurements
confirm both b and the retained ti have 44-unit lower bodies. All four rendered
PNGs were visually inspected. Local asset links, script syntax, brand exports,
and staged whitespace checks pass. The final changes are limited to brand assets
and this plan on the dedicated branding branch for PR #311.
