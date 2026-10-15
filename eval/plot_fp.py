#!/usr/bin/env python3
"""Figures for the score-separation study. Reads the JSON the study wrote."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

points = []
for name in ("fp_points.json", "fp_points_extra.json"):
    points.extend(json.loads((ROOT / "eval" / name).read_text())["points"])

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.6,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.grid": True,
    "grid.color": "#e4e0d8",
    "grid.linewidth": 0.5,
})

ARMS = [
    ("chrome_with_language", "Chrome, language set\nexisting pages"),
    ("chrome_human", "Headless Chrome\nexisting pages"),
    ("curl_browse", "curl 8.14.1\nexisting pages"),
    ("googlebot_polite", "Googlebot UA, polite\nunverified"),
    ("chrome_spa_paced", "Headless Chrome\n20 paced misses"),
    ("chrome_spa_burst_24", "Headless Chrome\n24 parallel misses"),
    ("curl_probe", "curl, 30 misses"),
    ("googlebot_scan", "Googlebot UA\n36 misses, unverified"),
    ("nikto_scan", "Nikto UA via httpx\nAccept still sent"),
    ("chrome_lang_burst_100", "Chrome, language set\n100 parallel misses"),
    ("nikto_headers", "Nikto headers\nboth header fields absent"),
    ("chrome_spa_burst_100", "Headless Chrome\n100 parallel misses"),
]


def finals(persona: str) -> list[dict]:
    last = {}
    for row in points:
        if row["persona"] == persona:
            last[row["session"]] = row
    return list(last.values())


fig, ax = plt.subplots(figsize=(7.4, 6.2))
ys = list(range(len(ARMS)))
for y, (key, _label) in enumerate(ARMS):
    rows = [row for row in points if row["persona"] == key]
    by_session = defaultdict(list)
    for row in rows:
        by_session[row["session"]].append(row)
    highs = [max(item["score"] for item in group) for group in by_session.values()]
    ends = [group[-1]["score"] for group in by_session.values()]
    held = any(item.get("hostile") for group in by_session.values() for item in group)
    color = "#c23b2e" if held else "#2f6f4e"
    if key == "chrome_lang_burst_100":
        color = "#b07d1a"
    ax.scatter(highs, [y] * len(highs), s=28, color=color, zorder=3, linewidths=0)
    if abs(sum(ends) / len(ends) - sum(highs) / len(highs)) > 0.05:
        ax.scatter(ends, [y] * len(ends), s=36, facecolors="none", edgecolors=color, zorder=4, linewidths=1.1)
ax.axvline(0.70, color="#c23b2e", lw=0.8, ls="--")
ax.axvline(0.40, color="#b07d1a", lw=0.7, ls=":")
ax.set_yticks(ys)
ax.set_yticklabels([label for _key, label in ARMS])
ax.set_xlabel("Highest S in the session  (open ring = score at the last request, if it fell)")
ax.set_xlim(0, 1.0)
ax.set_title("What the live gate scored, by client")
ax.annotate("gate 0.70", xy=(0.70, len(ARMS) - 0.55), xytext=(0.74, len(ARMS) - 0.55), color="#c23b2e", fontsize=8)
ax.annotate("watch 0.40", xy=(0.40, -0.35), color="#b07d1a", fontsize=8)
fig.tight_layout()
fig.savefig(OUT / "score_by_client.svg", bbox_inches="tight")
fig.savefig(OUT / "score_by_client.png", dpi=140, bbox_inches="tight")
plt.close()

TRAJ = [
    ("chrome_with_language", "Chrome + Accept-Language, real pages", "#2f6f4e"),
    ("chrome_human", "Headless Chrome, real pages", "#7aa88a"),
    ("chrome_spa_paced", "Headless Chrome, paced misses", "#b07d1a"),
    ("curl_probe", "curl, 30 misses", "#6b6258"),
    ("nikto_headers", "Nikto headers, misses", "#c23b2e"),
]
fig, ax = plt.subplots(figsize=(7.4, 4.4))
for key, label, color in TRAJ:
    by_step = defaultdict(list)
    for row in points:
        if row["persona"] == key:
            by_step[row["step"]].append(row["score"])
    steps = sorted(by_step)
    means = [sum(by_step[s]) / len(by_step[s]) for s in steps]
    ax.plot(steps, means, color=color, lw=1.6, label=label)
ax.axhline(0.70, color="#c23b2e", lw=0.7, ls="--")
ax.axhline(0.40, color="#b07d1a", lw=0.6, ls=":")
ax.set_xlabel("Request index in the session")
ax.set_ylabel("S")
ax.set_ylim(0, 1.0)
ax.set_title("Score along one scripted session")
ax.legend(frameon=False, fontsize=8, loc="lower right")
fig.tight_layout()
fig.savefig(OUT / "score_trajectory.svg", bbox_inches="tight")
fig.savefig(OUT / "score_trajectory.png", dpi=140, bbox_inches="tight")
plt.close()
print(OUT)
