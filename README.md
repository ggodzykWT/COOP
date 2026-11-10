# Whittier Tech Co-op Impact — Signage & Dashboard

Public GitHub Pages site: https://ggodzykwt.github.io/COOP/

## Files

| File | Purpose |
|---|---|
| `index.html` | Landing page linking to everything below |
| `whittier_tech_coop_impact_dashboard_signage.html` | All 5 scenes, auto-rotating on one page (browser / Rise Vision Web Page widget) |
| `whittier_tech_coop_signage_1_overview.html` … `_5_communities.html` | Individual scene pages, for platforms that rotate via their own playlist instead of JS |
| `whittier_tech_coop_signage_*.png` | Static 1920×1080 renders of each scene, for Rise Vision's Apple TV app (its Image slideshow, not the Web Page widget) |

## Data pipeline (in progress)

A co-op coordinator maintains partner data in a Google Sheet. A scheduled process pulls
that data, regenerates the HTML files above, and pushes the update here — GitHub Pages
republishes automatically within a couple minutes of any push to `main`.

The `.png` files are **not** part of that automated pipeline — they're a manual export
for Rise Vision and are refreshed by hand when needed.
