#!/usr/bin/env python3
"""Plot hotness score boundary violations across DRAM:NVM ratios for GapBS-BC."""
import os
import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

BASE = "/users/shelby/tiering_solutions/results/guardrail_analysis"

# Manually specify: use 72 for 1-8 (from old cba_on run)
RATIOS_DATA = [
    ("2:1", 0),
    ("1:1", 0),
    ("1:2", 8),
    ("1:4", 21),
    ("1:8", 72),
    ("1:16", 43),
]

DRAM_SIZES = {
    "2:1": 8.72,
    "1:1": 6.54,
    "1:2": 4.36,
    "1:4": 2.62,
    "1:8": 1.45,
    "1:16": 0.77,
}

if __name__ == '__main__':
    ratios = [r for r, _ in RATIOS_DATA]
    violations = [v for _, v in RATIOS_DATA]

    fig, ax = plt.subplots(figsize=(10, 5))

    x = np.arange(len(ratios))
    colors = ['#6C8EBF' if v > 0 else '#C8C8C8' for v in violations]
    edge_colors = ['#4A6A9B' if v > 0 else '#808080' for v in violations]

    ax.bar(x, violations, 0.6, color=colors, edgecolor=edge_colors, hatch='/', linewidth=1.2)

    # Add DRAM size labels below each bar
    for i, ratio in enumerate(ratios):
        ax.text(i, -4, f'{DRAM_SIZES[ratio]} GiB', ha='center', fontsize=8, color='#666666')

    ax.set_ylabel('Hotness Score Boundary Violations')
    ax.set_xlabel('DRAM:NVM Ratio')
    ax.set_xticks(x)
    ax.set_xticklabels(ratios)

    # Add annotation
    ax.annotate('More hot pages\nspill into NVM',
                xy=(0.75, 0.85), xycoords='axes fraction',
                fontsize=9, color='#666666',
                ha='center')
    ax.annotate('', xy=(0.9, 0.80), xycoords='axes fraction',
                xytext=(0.6, 0.80),
                arrowprops=dict(arrowstyle='->', color='#666666'))

    fig.suptitle('GapBS-BC: Hotness Score Boundary Violations Across DRAM:NVM Ratios',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    outpath = os.path.join(BASE, 'boundary_violations_ratios.png')
    plt.savefig(outpath, dpi=150)
    plt.close()
    print(f"Saved: {outpath}")
