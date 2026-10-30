"""Draw the three report charts from an evaluation summary.

draw_charts(summary, output_dir) writes three PNG files and returns their paths:

1. case_success.png - case success per arm, as n/N with a 95% Wilson interval.
2. user_impact.png  - mean user-impact seconds per arm, with a 95% bootstrap interval.
3. tokens_cost.png  - mean tokens and mean cost (USD) per arm, in two stacked panels.

Every chart is a dot-and-interval plot: one row per arm, a dot for the estimate,
a line for the interval and a text label with the numbers. A missing value is
written as "unavailable" (or "0/0 (not estimable)" for an empty rate), never
drawn as zero. Each chart carries the run's scope label so a synthetic preview
cannot be mistaken for evidence. The charts are descriptive: overlapping
intervals are not a statistical test.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

# Light-mode palette from the dataviz reference instance.
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"
ALERT = "#d03b3b"

ARM_ORDER = ["abcde", "runbook", "react", "naive_verify", "fifo"]
REFERENCE_ARMS = ["noop", "oracle"]
ARM_COLOURS = {
    "abcde": "#2a78d6",
    "runbook": "#eb6834",
    "react": "#1baf7a",
    "naive_verify": "#6250d6",
    "fifo": "#e87ba4",
    "noop": "#a8a69f",
    "oracle": "#52514e",
}
SPARE_COLOURS = ["#e34948", "#008300", "#eda100"]
ARM_LABELS = {
    "abcde": "ABCDE agent",
    "runbook": "Scripted runbook (no AI)",
    "react": "ReAct (free-form agent)",
    "naive_verify": "Naive verify (ablation)",
    "fifo": "FIFO order (ablation)",
    "noop": "No-op (reference)",
    "oracle": "Oracle (reference)",
}
STAGES = {
    "practice": "Practice: tuning cases dev-01 to dev-20 (not exam evidence)",
    "pilot": "Pilot: reserved cases dev-21 to dev-30, not tuned on (not exam evidence)",
    "exam": "Sealed exam (held-out cases)",
    "transfer": "Transfer exam (second test system)",
}
SPLITS = {
    "dev": "Development split: tuning cases dev-01 to dev-20 and pilot cases dev-21 to dev-30 (not exam evidence)",
    "heldout": STAGES["exam"],
    "transfer": STAGES["transfer"],
}
FOOTER = "Descriptive only. Overlapping intervals are not a test; paired comparisons are in report.md."

# Layout in inches, so headers and panels never collide whatever the row count.
WIDTH, ROW_H, HEADER_H, FOOTER_H, PANEL_GAP, PANEL_TITLE_H = 10.0, 0.55, 1.35, 0.95, 0.95, 0.3
AX_LEFT, AX_RIGHT, LABEL_X = 0.24, 0.66, 1.03


def arm_label(name):
    return ARM_LABELS.get(name, name)


def stage_label(summary):
    stage = summary.get("stage")
    if stage in STAGES:
        return STAGES[stage]
    split = summary.get("split")
    return SPLITS.get(split, f"Split: {split or 'unknown'}")


def ordered_arms(summary):
    """Arms in report order: headline pair, other agents, unknown arms, references."""
    arms = list(summary.get("arms") or [])
    rank = {name: i for i, name in enumerate(ARM_ORDER)}

    def key(arm):
        name = arm.get("name", "")
        if name in REFERENCE_ARMS:
            return (2, REFERENCE_ARMS.index(name), name)
        return (0, rank[name], name) if name in rank else (1, 0, name)

    return sorted(arms, key=key)


def arm_colours(arms):
    colours, spare = {}, iter(SPARE_COLOURS)
    for arm in arms:
        name = arm.get("name", "")
        colours[name] = ARM_COLOURS.get(name) or next(spare, MUTED)
    return colours


def is_synthetic(summary):
    label = (summary.get("scope_label") or "").lower()
    return "synthetic" in label or "fixture" in label


def fmt_number(value, kind):
    if value is None:
        return "unavailable"
    if kind == "seconds":
        return f"{value:,.1f} s"
    if kind == "tokens":
        return f"{value:,.0f}"
    if kind == "usd":
        return "$0" if value == 0 else f"${value:,.4f}"
    return f"{value:,.3g}"


def rate_text(rate):
    if not rate:
        return "not reported"
    n, total = rate.get("n"), rate.get("N")
    if not total:
        return f"{n or 0}/{total or 0} (not estimable)"
    est, low, high = rate.get("estimate"), rate.get("low"), rate.get("high")
    if est is None:
        return f"{n}/{total} (estimate unavailable)"
    interval = "interval unavailable" if low is None or high is None else f"{low:.0%}–{high:.0%}"
    return f"{n}/{total} · {est:.0%} [{interval}]"


def mean_text(mean, kind):
    if not mean or mean.get("mean") is None:
        n = (mean or {}).get("n")
        return "unavailable" + (f" · n={n}" if n is not None else "")
    value, low, high = mean["mean"], mean.get("low"), mean.get("high")
    if low is None or high is None:
        interval = " [interval unavailable]"
    elif low == high == value:
        interval = " (no spread)"
    else:
        interval = f" [{fmt_number(low, kind)}–{fmt_number(high, kind)}]"
    return f"{fmt_number(value, kind)}{interval} · n={mean.get('n')}"


def new_figure(summary, title, rows, panel_titles=None):
    """A figure with one axes per panel, stacked, each with its own x-axis."""
    panels = len(panel_titles) if panel_titles else 1
    title_h = PANEL_TITLE_H if panel_titles else 0
    panel_h = ROW_H * max(rows, 1) + 0.2
    height = HEADER_H + FOOTER_H + panels * (panel_h + title_h) + (panels - 1) * PANEL_GAP
    fig = plt.figure(figsize=(WIDTH, height), facecolor=SURFACE)
    axes, top = [], height - HEADER_H
    for i in range(panels):
        top -= title_h
        bottom = top - panel_h
        ax = fig.add_axes([AX_LEFT, bottom / height, AX_RIGHT - AX_LEFT, panel_h / height])
        if panel_titles:
            fig.text(AX_LEFT, (top + 0.08) / height, panel_titles[i], fontsize=10.5,
                     fontweight="bold", color=INK, va="bottom")
        axes.append(ax)
        top = bottom - PANEL_GAP

    def y(inches_from_top):
        return 1 - inches_from_top / height

    fig.text(0.015, y(0.3), title, fontsize=13, fontweight="bold", color=INK, va="center")
    subtitle = f"Run {summary.get('run', '?')} · {stage_label(summary)} · condition {summary.get('condition', '?')}"
    fig.text(0.015, y(0.6), subtitle, fontsize=9, color=INK_2, va="center")
    fig.text(0.015, y(0.92), summary.get("scope_label") or "Scope not stated",
             fontsize=9, fontweight="bold", color=INK, va="center",
             bbox={"boxstyle": "round,pad=0.3", "facecolor": SURFACE, "edgecolor": ALERT, "linewidth": 1.5})
    fig.text(0.015, 0.22 / height, FOOTER, fontsize=8, color=INK_2, va="center")
    if is_synthetic(summary):
        plot_h = height - HEADER_H - FOOTER_H
        centre = (FOOTER_H + plot_h / 2) / height
        fig.text((AX_LEFT + AX_RIGHT) / 2, centre, "SYNTHETIC", fontsize=min(56, 20 * plot_h),
                 color=ALERT, alpha=0.07, rotation=15, ha="center", va="center", fontweight="bold", zorder=0)
    return fig, axes


def style_axis(ax, arms, xlabel):
    ax.set_facecolor("none")
    ax.set_yticks(range(len(arms)))
    ax.set_yticklabels([arm_label(a.get("name", "")) for a in arms], color=INK, fontsize=10)
    ax.set_ylim(len(arms) - 0.5, -0.5)
    ax.set_xlabel(xlabel, color=INK_2, fontsize=9)
    ax.tick_params(axis="x", colors=MUTED, labelsize=8)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)


def draw_rows(ax, arms, colours, points, labels):
    """points: per arm (estimate, low, high) or None; labels: text per arm."""
    for row, (arm, point, text) in enumerate(zip(arms, points, labels)):
        colour = colours[arm.get("name", "")]
        if point is not None:
            est, low, high = point
            if low is not None and high is not None and low != high:
                ax.hlines(row, low, high, color=colour, linewidth=2, zorder=2)
                ax.vlines([low, high], row - 0.12, row + 0.12, color=colour, linewidth=2, zorder=2)
            ax.plot(est, row, "o", markersize=9, color=colour, clip_on=False,
                    markeredgecolor=SURFACE, markeredgewidth=2, zorder=3)
        ax.text(LABEL_X, row, text, va="center", fontsize=9,
                color=INK if point is not None else INK_2, transform=ax.get_yaxis_transform())


def no_values(ax, arms, text):
    """Keep the arm rows readable but drop the meaningless x-axis."""
    ax.set_xticks([])
    ax.set_xlabel("")
    ax.grid(False)
    ax.spines["bottom"].set_visible(False)
    ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=9, color=INK_2, transform=ax.transAxes)


def empty_message(ax, text):
    ax.set_axis_off()
    ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=11, color=INK_2, transform=ax.transAxes)


def set_xlim(ax, points):
    """Start at zero (or below, for negative values) with a small margin so dots at 0 are not clipped."""
    values = [v for p in points if p for v in p if v is not None]
    low, high = min(0, min(values, default=0)), max(values, default=0)
    high = high * 1.08 if high > 0 else 1
    pad = (high - low) * 0.03
    ax.set_xlim(low - pad, high)


def draw_case_success(summary, arms, colours, path):
    fig, (ax,) = new_figure(summary, "Case success by arm (primary endpoint)", len(arms))
    if not arms:
        empty_message(ax, "No arms in this summary")
    else:
        rates = [(a.get("rates") or {}).get("case_success") for a in arms]
        points = [(r["estimate"], r.get("low"), r.get("high")) if r and r.get("N") and r.get("estimate") is not None
                  else None for r in rates]
        style_axis(ax, arms, "Cases that succeeded (%) · dot = estimate, line = 95% Wilson interval")
        ax.set_xlim(-0.03, 1.0)
        ax.xaxis.set_major_formatter(PercentFormatter(1.0))
        draw_rows(ax, arms, colours, points, [rate_text(r) for r in rates])
        if not any(points):
            no_values(ax, arms, "No case-success estimate available")
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def mean_points(arms, metric):
    means = [(a.get("means") or {}).get(metric) for a in arms]
    points = [(m["mean"], m.get("low"), m.get("high")) if m and m.get("mean") is not None else None
              for m in means]
    return means, points


TICK_FORMATS = {
    "seconds": FuncFormatter(lambda v, _: f"{v:,.0f} s"),
    "tokens": FuncFormatter(lambda v, _: f"{v:,.0f}"),
    "usd": FuncFormatter(lambda v, _: f"${v:,.2f}"),
}


def draw_mean_panel(ax, arms, colours, metric, kind, xlabel):
    means, points = mean_points(arms, metric)
    style_axis(ax, arms, xlabel)
    set_xlim(ax, points)
    ax.xaxis.set_major_formatter(TICK_FORMATS[kind])
    draw_rows(ax, arms, colours, points, [mean_text(m, kind) for m in means])
    if not any(points):
        no_values(ax, arms, "No values available for any arm")


def draw_user_impact(summary, arms, colours, path):
    fig, (ax,) = new_figure(summary, "User-impact seconds by arm (lower is better)", len(arms))
    if not arms:
        empty_message(ax, "No arms in this summary")
    else:
        draw_mean_panel(ax, arms, colours, "user_impact_s", "seconds",
                        "Mean seconds below the SLO per case · dot = mean, line = 95% bootstrap interval")
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def draw_tokens_cost(summary, arms, colours, path):
    titles = ["Mean model tokens per case", "Mean model cost per case (USD)"]
    fig, axes = new_figure(summary, "Model tokens and cost per case by arm", len(arms), panel_titles=titles)
    panels = [("tokens", "tokens"), ("cost_usd", "usd")]
    for ax, (metric, kind) in zip(axes, panels):
        if not arms:
            empty_message(ax, "No arms in this summary")
            continue
        # Separate stacked panels, each with its own x-axis: never a dual axis.
        draw_mean_panel(ax, arms, colours, metric, kind, "dot = mean, line = 95% bootstrap interval")
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def draw_charts(summary: dict, output_dir: Path) -> list[Path]:
    """Write the three charts into output_dir and return their paths, in report order."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    arms = ordered_arms(summary)
    colours = arm_colours(arms)
    paths = [output_dir / "case_success.png", output_dir / "user_impact.png", output_dir / "tokens_cost.png"]
    draw_case_success(summary, arms, colours, paths[0])
    draw_user_impact(summary, arms, colours, paths[1])
    draw_tokens_cost(summary, arms, colours, paths[2])
    return paths
