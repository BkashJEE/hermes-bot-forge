#!/usr/bin/env bash
# Rebuild the social card: the layout is an SVG, the hero artwork is composited over it, so the
# two can change independently. Run from the repo root.
set -euo pipefail
rsvg-convert -w 1280 -h 640 docs/social-card.svg -o /tmp/bot-forge-card-bg.png
magick /tmp/bot-forge-card-bg.png \
  \( docs/hero-character.png -resize x600 \) -gravity southwest -geometry +56+6 -composite \
  docs/social-preview.png
magick docs/social-preview.png -resize 1200x600! docs/banner.png
echo "wrote docs/social-preview.png and docs/banner.png"
