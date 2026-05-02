#!/usr/bin/env python3
"""Plot DRAM BW over time showing dip-and-recovery around RECN mode transitions."""
import os
import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

BASE = "/users/shelby/tiering_solutions/results/guardrail_analysis"


def extract_data(filepath):
    dram_bw = []
    dram_bw_ewma = []
    violations = []  # indices where violations occurred
    recn_starts = []
    recn_ends = []
    bw_idx = 0

    mode = "hist"
    with open(filepath) as f:
        for line in f:
            if "Switching to RECN" in line:
                mode = "recn"
                recn_starts.append(bw_idx)
            elif "Switching back to HIST" in line:
                mode = "hist"
                recn_ends.append(bw_idx)

            m = re.search(r'DRAM_BW: ([\d.]+) GB/s \(ewma=([\d.]+)\)', line)
            if m:
                dram_bw.append(float(m.group(1)))
                dram_bw_ewma.append(float(m.group(2)))
                bw_idx += 1

            if "MIG_EFF VIOLATION" in line:
                violations.append(bw_idx - 1)

    return dram_bw, dram_bw_ewma, violations, recn_starts, recn_ends


if __name__ == '__main__':
    filepath = "/users/shelby/tiering_solutions/src/liblinear_bw_recovery.txt"

    dram_bw, ewma, violations, recn_starts, recn_ends = extract_data(filepath)

    n = len(dram_bw)
    x = np.arange(n)

    fig, ax = plt.subplots(figsize=(14, 5))

    # Plot raw BW
    ax.plot(x, dram_bw, alpha=0.4, color='#6C8EBF', linewidth=0.8, label='DRAM BW')

    # Plot EWMA
    ax.plot(x, ewma, color='#6C8EBF', linewidth=2.0, label='DRAM BW EWMA')

    # Mark violations
    viol_x = [v for v in violations if v < n]
    viol_y = [dram_bw[v] for v in viol_x]
    ax.scatter(viol_x, viol_y, color='#B85450', marker='x', s=20, zorder=5, alpha=0.7, label='Mig Eff Violation')

    # Shade RECN regions
    for i, (s, e) in enumerate(zip(recn_starts, recn_ends)):
        if s < n and e < n:
            ax.axvspan(s, e, alpha=0.2, color='orange',
                       label='RECN mode' if i == 0 else None)

    ax.set_ylabel('DRAM Bandwidth (GB/s)')
    ax.set_xlabel('BW Measurement Interval (~1 second each)')
    ax.legend(loc='upper right', fontsize=9)

    fig.suptitle('Liblinear Migration Effectiveness Violations Over Time',
                 fontsize=12, fontweight='bold')
    plt.tight_layout()
    outpath = os.path.join(BASE, 'liblinear_bw_recovery.png')
    plt.savefig(outpath, dpi=150)
    plt.close()
    print(f"Saved: {outpath}")
