"""Render the defect-vs-release matrix used in the README and write-ups.

Every cell is a claim HISTORY.md already backs with a file:line citation.
Run: python3 assets/make_matrix.py
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

RELEASES = ["rc.6\n08-13", "rc.7\n08-17", "rc.8\n08-19", "rc.1\n08-21",
            "rc.2\n08-21", "α.1\n08-27", "α.2\n08-30"]

# "-" not yet found / not applicable, "x" present, "v" fixed upstream
ROWS = [
    ("P2  BOM crash on plugin add",        "xxxxxxx"),
    ("P3  web fence (#2573)",              "xxxxx" "vv"),
    ("P4  spillAll unguarded",             "xxxxxxx"),
    ("P5  session log seq gap",            "xxxxxxx"),
    ("P6  env scrub false positive",       "--xxxxx"),
    ("P7  codex preflight crash",          "--xxxxx"),
    ("P8  multimodal half-turn",           "--xxxxx"),
    ("P9  Files quota cross-install",      "----xxx"),
    ("P10 jsonl repair unguarded",         "-----xx"),
]

PRESENT, FIXED, NA = "#dc2626", "#22c55e", "#e5e7eb"
BG, FG, MUTED = "#0d1117", "#e6edf3", "#8b949e"

fig, ax = plt.subplots(figsize=(11, 5.6))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)

for r, (label, cells) in enumerate(ROWS):
    y = len(ROWS) - r - 1
    ax.text(-0.25, y + 0.5, label, ha="right", va="center",
            fontsize=10.5, color=FG, family="monospace")
    for c, mark in enumerate(cells):
        color = {"x": PRESENT, "v": FIXED, "-": NA}[mark]
        ax.add_patch(Rectangle((c, y), 0.9, 0.9, facecolor=color,
                               edgecolor=BG, linewidth=2))
        if mark == "v":
            ax.text(c + 0.45, y + 0.45, "✓", ha="center", va="center",
                    fontsize=15, color="#0d1117", weight="bold")

for c, rel in enumerate(RELEASES):
    ax.text(c + 0.45, len(ROWS) + 0.15, rel, ha="center", va="bottom",
            fontsize=9.5, color=MUTED, family="monospace")

ax.set_xlim(-5.6, len(RELEASES) + 0.2)
ax.set_ylim(-1.5, len(ROWS) + 1.1)
ax.axis("off")

ax.text(-5.5, len(ROWS) + 0.15, "dsh doctor --node",
        fontsize=15, color=FG, weight="bold", family="monospace", va="bottom")

legend = [(PRESENT, "still present"), (FIXED, "fixed upstream"), (NA, "not yet reported")]
for i, (color, text) in enumerate(legend):
    x = -5.5 + i * 1.85
    ax.add_patch(Rectangle((x, -1.15), 0.32, 0.32, facecolor=color, edgecolor=BG))
    ax.text(x + 0.45, -1.0, text, fontsize=9, color=MUTED, va="center")

ax.text(len(RELEASES) + 0.1, -1.0,
        "1 of 9 fixed in 17 days · every cell cites a file:line in HISTORY.md",
        fontsize=8.5, color=MUTED, ha="right", va="center", style="italic")

plt.tight_layout()
plt.savefig("assets/defect-matrix.png", dpi=200, facecolor=BG, bbox_inches="tight")
print("wrote assets/defect-matrix.png")
