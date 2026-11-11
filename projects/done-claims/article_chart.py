"""Draw the within-issue odds ratios of every phase for the article, in English or Turkish.

    uv run python article_chart.py OUT.png [--lang tr]      (from projects/done-claims)

Every value is read from the committed result files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
COMPARISON = "unverified vs ran_passing"
P2B = "results/phase2b/analysis.json"
TEXT = {
    "en": {
        "rows": ("Phase 1: SWE-agent, Llama-based models", "Phase 2a: Claude Code + gpt-oss-120b",
                 "Phase 2b, stage 1 only", "Phase 2b, stages pooled (H1)"),
        "issues": "issues",
        "title": "Within-issue odds ratio of resolving the issue: unverified / ran_passing",
        "note": "Mantel-Haenszel odds ratio, strata = issue; 95% CI (Robins-Breslow-Greenland); log scale.\n"
                "Below 1: lower odds of resolution when no test or script ran after the last edit. "
                "H1: the planned primary analysis.",
    },
    "tr": {
        "rows": ("Faz 1: SWE-agent, Llama tabanlı modeller", "Faz 2a: Claude Code + gpt-oss-120b",
                 "Faz 2b, yalnızca 1. aşama", "Faz 2b, iki aşama birlikte (H1)"),
        "issues": "görev",
        "title": "Aynı görev içinde odds oranı: unverified / ran_passing",
        "note": "Mantel-Haenszel odds oranı, her görev ayrı bir tabaka; %95 GA (Robins-Breslow-Greenland); "
                "logaritmik eksen.\n1'in altı: son düzenlemeden sonra test ya da betik çalıştırılmadıysa "
                "çözülme odds'u daha düşük. H1: planlanan ana analiz.",
    },
}


def estimate(rel: str, *keys: str) -> dict:
    data = json.loads((HERE / rel).read_text(encoding="utf-8"))
    for key in keys:
        data = data[key]
    return next(row for row in data if row["comparison"] == COMPARISON)


def rows() -> list[dict]:
    within = ("stratified_odds_ratios", "within_instance")
    return [
        estimate("results/summary.json", "submitted", *within),
        estimate("results/phase2/full-gptoss-instr/summary.json", "completed", *within),
        estimate(P2B, "stage1", "odds_ratios"),
        estimate(P2B, "pooled", "odds_ratios"),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=tuple(TEXT), default="en")
    args = parser.parse_args()
    t = TEXT[args.lang]

    def num(x: float) -> str:
        s = f"{x:.2f}"
        return s.replace(".", ",") if args.lang == "tr" else s

    data = rows()
    fig, ax = plt.subplots(figsize=(8, 3.3), dpi=200)
    for i, row in enumerate(data):
        y = len(data) - 1 - i
        lo, hi = row["ci95"]
        color = "#b03a2e" if i == len(data) - 1 else "#34495e"
        ax.plot([lo, hi], [y, y], color=color, linewidth=2.2, solid_capstyle="butt")
        ax.plot(row["odds_ratio"], y, marker="s", markersize=7, color=color)
        text = f"{num(row['odds_ratio'])} ({num(lo)}–{num(hi)}), {row['informative_strata']} {t['issues']}"
        ax.text(1.02, y, text, transform=ax.get_yaxis_transform(), va="center", fontsize=8.5)
    ax.axvline(1, color="#7f8c8d", linestyle="--", linewidth=1)
    ax.set_xscale("log")
    ticks = [0.25, 0.5, 1, 2, 4]
    labels = [f"{v:g}".replace(".", ",") if args.lang == "tr" else f"{v:g}" for v in ticks]
    ax.set_xticks(ticks, labels)
    ax.minorticks_off()
    ax.set_xlim(0.25, 4)
    ax.set_ylim(-0.6, len(data) - 0.4)
    ax.set_yticks(range(len(data)), list(reversed(t["rows"])), fontsize=9)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="y", length=0)
    fig.text(0.01, 0.97, t["title"], fontsize=10.5, va="top")
    fig.text(0.01, 0.03, t["note"], fontsize=7.5, color="#555555")
    fig.subplots_adjust(left=0.37, right=0.76, top=0.86, bottom=0.3)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    print(args.out)


if __name__ == "__main__":
    main()
