# Artwork and layout notes

## Cover

- Asset: `agent-receipt-cover.png`
- Created with the built-in `image_gen` tool; no external reference images.
- Actual dimensions: 1774 x 887 pixels (2:1).
- Original PNG size: 1,948,224 bytes.
- The original PNG is preserved. `agent-receipt-social.jpg` is the same artwork
  exported as JPEG for web delivery, with no crop, resize or layout change.
  It is 1774x887 pixels, 140,307 bytes and within GitHub's social-preview limits.
  The JPEG is used in the README and article; the repository social-preview setting
  itself has not been applied.
- Palette: paper #F3F0E9, ink #17242D, orange #D96742, green #527A67.
- No badges, usage statistics or adoption claims are part of the artwork.

### Exact generation prompt

```text
Create one polished editorial cover image for an open-source Python developer tool named Agent Receipt. Intended use: GitHub README hero and social sharing. Wide landscape composition, exact 2:1 aspect ratio, ideally 1280 x 640 px. Flat front-facing graphic design, crisp and restrained, high contrast, very generous spacing, not a screenshot, no 3D mockup of a website.
Palette: warm off-white #F3F0E9 background, very dark blue-black #17242D typography, restrained burnt orange #D96742 accents, muted green #527A67 for a verified status. Very subtle print-paper texture. Modern Swiss editorial typography with a bold sans-serif headline and small monospace technical labels.
Left two thirds: small uppercase eyebrow "OPEN TOOLS FOR AI AGENTS"; huge exact title "Agent Receipt"; below it the exact large subtitle on two lines "A timeout isn't" and "a failed write."; small bottom line exact text "PYTHON  /  SQLITE  /  ASYNC  /  MIT". Keep all lettering unambiguous and easily readable at a 640px-wide preview.
Right third: an elegant original schematic illustration of a durable paper receipt with a neat small orange corner fold. Three simple stacked horizontal signal lines, connected with a fine vertical line, labelled exactly "RESERVE", "UNKNOWN", "VERIFY". A single outlined checkmark at the bottom represents a separate trusted verification step. Do not label an ordinary tool response as verified. Thin ink rules and one orange dashed response path ending short illustrate a missing response. Treat this as an editorial illustration of uncertain delivery, not a claim of exactly-once delivery or production certification.
Avoid generic robots, human faces, brains, neon gradients, glowing cyberpunk, fake metrics, badges of certification, trophies, social proof, extra text, watermarks, existing third-party logos. All content must sit well within 6% outer margins. Final image should feel like a thoughtful small engineering project, clear enough to understand at a glance.
```

## State diagram

`receipt-states.svg` is an original, editable code-native diagram. Its text mirrors
the library states. A recorded response is distinct from trusted positive
verification; neither an empty lookup nor cancellation releases a reservation.
The SVG contains no script, foreignObject, external references or tracking.

## Accessible use

The README and article include descriptive alt text. Technical explanations and
the quickstart remain selectable text outside the artwork. All images have solid
backgrounds, so their content remains readable in light and dark GitHub themes.

