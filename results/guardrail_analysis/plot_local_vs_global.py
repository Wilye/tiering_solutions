#!/usr/bin/env python3
"""Plot hotness score and DRAM access fraction violations together for GapBS-BC."""
import os
import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

BASE = "/users/shelby/tiering_solutions/results/guardrail_analysis"


filepath = f"{BASE}/xsbench_and_bc_twitter/gapbs_bc_twitter_1-8_normal_run1.txt"

fracs = []
ewmas = []
hotness_viols = []
frac_viols = []
interval = 0

with open(filepath) as f:
    for line in f:
        m = re.search(r'DRAM_ACCESS_FRACTION: ([\d.]+) \(ewma=([\d.]+)', line)
        if m:
            fracs.append(float(m.group(1)))
            ewmas.append(float(m.group(2)))
            interval += 1

        if "HOTNESS_SCORE VIOLATION" in line:
            hotness_viols.append(interval - 1)

        if "DRAM_ACCESS_FRACTION VIOLATION" in line:
            frac_viols.append(interval - 1)

n = len(fracs)
x = np.arange(n)

fig, ax = plt.subplots(figsize=(12, 4.5))

# EWMA line
ax.plot(x, ewmas, color='#6C8EBF', linewidth=1.2, label='DRAM Fraction EWMA', zorder=2)

# Hotness score violations - mark on the EWMA line
if hotness_viols:
    hot_y = [ewmas[v] for v in hotness_viols if v < n]
    hot_x = [v for v in hotness_viols if v < n]
    ax.scatter(hot_x, hot_y, color='#9673A6', marker='^', s=30, zorder=5,
               alpha=0.8, label='Boundary Violation')

ax.set_ylabel('DRAM Access Fraction')
ax.set_xlabel('Interval')
ax.set_ylim(-0.05, 1.05)
ax.legend(loc='upper right', fontsize=9)

fig.suptitle('GapBS-BC: Local vs Global Guardrail Violations (1:8)',
             fontsize=12, fontweight='bold')
plt.tight_layout()
outpath = os.path.join(BASE, 'local_vs_global_gapbs_bc.png')
plt.savefig(outpath, dpi=150)
plt.close()
print(f"Saved: {outpath}")
