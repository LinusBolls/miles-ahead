"""Draw the two README figures from the reported numbers. Measured points only: no interpolation, no fitted curves.

  docs/fig_stranding_auc.{svg,png}  Berlin stranding, AUC by training rows (Table 1 of the whitepaper)
  docs/fig_coldstart.{svg,png}      new-city cold start, two separate runs in two separate panels

Usage: uv run --with matplotlib --with pandas python docs/make_figures.py
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
COLD_CSV = os.path.join(HERE, "..", "miles-ops", "analysis", "coldstart_results_off.csv")

BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#8a8984"   # categorical slots 1-2 + neutral
INK, INK2, GRID, BG = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9.5, "axes.edgecolor": INK2, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": BG, "axes.facecolor": BG, "svg.fonttype": "none",
})


def style(ax):
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def save(fig, name):
    for ext in ("svg", "png"):
        fig.savefig(os.path.join(HERE, f"{name}.{ext}"), dpi=200 if ext == "png" else None, bbox_inches="tight",
                    metadata={"Date": None} if ext == "svg" else None)
    plt.close(fig)


# --- Figure 1: stranding, Berlin, test 17-22 June 2024 (teammate's Prior Labs API run; see README) ---------------
fig, ax = plt.subplots(figsize=(6.4, 3.6))
style(ax)
ax.set_xscale("log")
pts = [  # (rows, auc, label, colour, marker, filled)
    (10_000, 0.846, "TabPFN, 10k context\nAUC 0.846 · ECE 0.010", BLUE, "o", True),
    (10_000, 0.825, "GBM, same 10k rows\nAUC 0.825 · ECE 0.030", ORANGE, "o", False),
    (208_000, 0.858, "GBM, all 208k rows\nAUC 0.858 · ECE 0.008", ORANGE, "o", False),
    (208_000, 0.806, "Logistic, 208k rows\nAUC 0.806", GRAY, "s", False),
]
for x, y, lab, c, m, filled in pts:
    ax.plot([x], [y], m, ms=9, mfc=c if filled else BG, mec=c, mew=2, zorder=3)
    left = x > 50_000
    ax.annotate(lab, (x, y), xytext=(-12 if left else 12, 0), textcoords="offset points", va="center",
                ha="right" if left else "left", color=INK, fontsize=8.5)
ax.set_xlim(4_000, 600_000)
ax.set_ylim(0.795, 0.868)
ax.set_xticks([10_000, 208_000])
ax.set_xticklabels(["10k rows (5%)", "208k rows (all)"])
ax.minorticks_off()
ax.set_ylabel("AUC, test days 17-22 June")
ax.set_title("Stranding (idle > 12 h after ride end), Berlin. GBM on all data edges TabPFN;\n"
             "at the same 10k rows TabPFN is ahead and 3x better calibrated.", loc="left", fontsize=9.5, color=INK)
save(fig, "fig_stranding_auc")

# --- Figure 2: cold start, two runs, two panels --------------------------------------------------------------------
cold = pd.read_csv(COLD_CSV)
means = cold.groupby("n")[["ber_transfer_auc", "gbm_auc"]].mean()
print("coldstart_results_off.csv means by n:\n", means.round(3).to_string())

fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.6, 3.6), sharey=True)
for ax in (a1, a2):
    style(ax)
    ax.set_xscale("log")
    ax.set_xticks([50, 100, 200, 500, 1000])
    ax.set_xticklabels(["50", "100", "200", "500", "1000"])
    ax.minorticks_off()
    ax.set_xlabel("local ride ends in the new city")
    ax.set_xlim(38, 1500)
a1.set_ylim(0.53, 0.73)
a1.set_ylabel("AUC, stranding in a new city")

# Run A: teammate's Prior Labs API run (scripts pending). TabPFN measured at n = 50, 200, 1000 only.
tn, ta = [50, 200, 1000], [0.665, 0.688, 0.710]
a1.plot(tn, ta, "-o", color=BLUE, lw=2, ms=8, mec=BG, mew=1.5, label="TabPFN, Berlin + local rides as context")
for x, y in zip(tn, ta):
    a1.annotate(f"{y:.3f}", (x, y), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8, color=INK)
# same-run best GBM, reported only approximately and only at n = 50 and 1000 (not run at 200): unconnected markers
for x, y in [(50, 0.61), (1000, 0.65)]:
    a1.plot([x], [y], "o", ms=8, mfc=BG, mec=ORANGE, mew=2)
    a1.annotate(f"≈{y:.2f}", (x, y), xytext=(0, -14), textcoords="offset points", ha="center", fontsize=8, color=INK)
a1.plot([], [], "o", ms=8, mfc=BG, mec=ORANGE, mew=2, label="best GBM, same run (approx., n=200 not run)")
a1.set_title("Run A: Prior Labs API (teammate's run,\nscripts pending)", loc="left", fontsize=9.5, color=INK)
a1.legend(loc="lower right", fontsize=7.8, frameon=False)

# Run B: committed script, mean over 6 cities x 3 seeds (AGB has no n = 1000 pool)
n = means.index.values
a2.plot(n, means.ber_transfer_auc, "-o", color=ORANGE, lw=2, ms=7, mec=BG, mew=1.5, label="GBM trained on Berlin only (transfer)")
a2.plot(n, means.gbm_auc, "--s", color=GRAY, lw=2, ms=6, mec=BG, mew=1.5, label="GBM trained on local rides only")
for col in ("ber_transfer_auc", "gbm_auc"):
    for x in (50, 1000):
        y = means.loc[x, col]
        a2.annotate(f"{y:.3f}", (x, y), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8, color=INK)
a2.set_title("Run B: miles-ops/analysis/coldstart.py --tabpfn off\n(coldstart_results_off.csv, 6 cities x 3 seeds)",
             loc="left", fontsize=9.5, color=INK)
a2.legend(loc="lower right", fontsize=7.8, frameon=False)
fig.suptitle("Cold start. The two panels are different runs; compare within a panel, not across.",
             x=0.01, ha="left", fontsize=9.5, color=INK2, y=1.04)
save(fig, "fig_coldstart")
