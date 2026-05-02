#!/usr/bin/env python3
"""Plot hotness score boundary violations over time for GapBS-BC."""
import os
import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

BASE = "/users/shelby/tiering_solutions/results/guardrail_analysis"


def plot(filepath, title, outpath):
    dram_avgs = []
    nvm_avgs = []
    violation_intervals = []
    interval = 0

    with open(filepath) as f:
        for line in f:
            m = re.search(r'HOTNESS_SCORE boundary: avg_dram=([\d.]+).*avg_nvm=([\d.]+)', line)
            if m:
                dram_avgs.append(float(m.group(1)))
                nvm_avgs.append(float(m.group(2)))
                interval += 1

            if "HOTNESS_SCORE VIOLATION" in line:
                violation_intervals.append(interval - 1)

    n = len(dram_avgs)
    x = np.arange(n)

    fig, ax = plt.subplots(figsize=(12, 4.5))

    ax.plot(x, dram_avgs, color='#6C8EBF', linewidth=1.0, alpha=0.7, label='DRAM side avg accesses')
    ax.plot(x, nvm_avgs, color='#B85450', linewidth=1.0, alpha=0.7, label='NVM side avg accesses')

    # Mark violations
    if violation_intervals:
        viol_y = [nvm_avgs[v] for v in violation_intervals if v < n]
        viol_x = [v for v in violation_intervals if v < n]
        ax.scatter(viol_x, viol_y, color='#B85450', marker='x', s=20, zorder=5, alpha=0.7, label='Boundary Violation')

    ax.set_ylabel('Avg Raw Accesses per Page')
    ax.set_xlabel('Boundary Check Interval')
    ax.legend(loc='upper right', fontsize=8)

    fig.suptitle(title, fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()
    print(f"Saved: {outpath}")


if __name__ == '__main__':
    f = f"{BASE}/xsbench_and_bc_twitter/gapbs_bc_twitter_1-8_cba_on_run1.txt"
    if os.path.exists(f):
        plot(f,
             "GapBS-BC Hotness Score Boundary Over Time (1:8)",
             os.path.join(BASE, "boundary_timeseries_gapbs_bc.png"))
