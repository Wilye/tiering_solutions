#!/usr/bin/env python3
"""Plot DRAM access fraction EWMA with total accesses shaded behind."""
import os
import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

BASE = "/users/shelby/tiering_solutions/results/guardrail_analysis"


def plot(filepath, title, outpath, skip=0):
    ewmas = []
    totals = []
    recn_starts = []
    recn_ends = []
    interval = 0

    with open(filepath) as f:
        for line in f:
            if "Switching to RECN" in line:
                recn_starts.append(interval)
            elif "Switching back to HIST" in line:
                recn_ends.append(interval)
            m = re.search(r'DRAM_ACCESS_FRACTION: [\d.]+ \(ewma=([\d.]+).*total=(\d+)', line)
            if m:
                ewmas.append(float(m.group(1)))
                totals.append(int(m.group(2)))
                interval += 1

    # Skip startup
    ewmas = ewmas[skip:]
    totals = totals[skip:]
    recn_starts = [r - skip for r in recn_starts if r >= skip]
    recn_ends = [r - skip for r in recn_ends if r >= skip]

    n = len(ewmas)
    x = np.arange(n)

    # Smooth totals only (EWMA is already smooth)
    kernel = 30
    totals_smooth = np.convolve(totals, np.ones(kernel) / kernel, mode='valid')
    x_totals = np.arange(len(totals_smooth))

    fig, ax1 = plt.subplots(figsize=(12, 4.5))

    # Gray shading: total accesses
    ax2 = ax1.twinx()
    ax2.fill_between(x_totals, 0, totals_smooth, alpha=0.15, color='#808080',
                     label='Total PEBS Accesses')
    ax2.set_ylabel('Total Accesses (smoothed)', color='#808080')
    ax2.tick_params(axis='y', labelcolor='#808080')

    # Blue line: EWMA fraction
    ax1.plot(x, ewmas, color='#6C8EBF', linewidth=1.2, label='DRAM Fraction EWMA', zorder=3)

    # Orange shading: RECN mode
    for i, (s, e) in enumerate(zip(recn_starts, recn_ends)):
        if 0 <= s < n and 0 <= e < n:
            ax1.axvspan(s, e, alpha=0.15, color='orange',
                        label='RECN mode' if i == 0 else None)

    ax1.set_ylabel('DRAM Access Fraction', color='#6C8EBF')
    ax1.set_xlabel('Interval (after startup)')
    ax1.set_ylim(-0.05, 1.05)
    ax1.tick_params(axis='y', labelcolor='#6C8EBF')

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc='upper right', fontsize=8)

    fig.suptitle(title, fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()
    print(f"Saved: {outpath}")


if __name__ == '__main__':
    f = "/users/shelby/tiering_solutions/src/liblinear_bw_recovery.txt"
    if os.path.exists(f):
        plot(f,
             "Liblinear DRAM Access Fraction and Memory Intensity",
             os.path.join(BASE, "fraction_with_intensity_liblinear.png"))
