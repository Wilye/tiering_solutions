#!/usr/bin/env python3
"""Plot DRAM vs NVM accesses to show placement quality during violation vs non-violation periods."""
import os
import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

BASE = "/users/shelby/tiering_solutions/results/guardrail_analysis"


def extract_data(filepath):
    dram_acc = []
    nvm_acc = []
    totals = []
    modes = []
    mode = "hist"

    with open(filepath) as f:
        for line in f:
            if "Switching to RECN" in line:
                mode = "recn"
            elif "Switching back to HIST" in line:
                mode = "hist"
            m = re.search(r'DRAM_ACCESS_FRACTION:.*dram_accesses=(\d+), nvm_accesses=(\d+), total=(\d+)', line)
            if m:
                dram_acc.append(int(m.group(1)))
                nvm_acc.append(int(m.group(2)))
                totals.append(int(m.group(3)))
                modes.append(mode)

    return dram_acc, nvm_acc, totals, modes


def plot_stacked_bars(dram_acc, nvm_acc, totals, outpath):
    """Stacked bar chart: violation vs non-violation intervals."""
    median_total = np.median(totals)

    # Only look at high-access intervals (above median)
    high_acc_good = {'dram': [], 'nvm': []}
    high_acc_bad = {'dram': [], 'nvm': []}

    for d, n, t in zip(dram_acc, nvm_acc, totals):
        if t < median_total:
            continue
        frac = d / t if t > 0 else 0
        if frac >= 0.5:
            high_acc_good['dram'].append(d)
            high_acc_good['nvm'].append(n)
        else:
            high_acc_bad['dram'].append(d)
            high_acc_bad['nvm'].append(n)

    fig, ax = plt.subplots(figsize=(8, 5))

    labels = ['Good Placement\n(Fraction >= 0.5)', 'Bad Placement\n(Fraction < 0.5)']
    dram_means = [np.mean(high_acc_good['dram']), np.mean(high_acc_bad['dram'])]
    nvm_means = [np.mean(high_acc_good['nvm']), np.mean(high_acc_bad['nvm'])]

    x = np.arange(len(labels))
    width = 0.5

    ax.bar(x, dram_means, width, label='DRAM Accesses', color='#6C8EBF', edgecolor='#4A6A9B')
    ax.bar(x, nvm_means, width, bottom=dram_means, label='NVM Accesses', color='#B85450', edgecolor='#963E3A')

    # Add count annotations
    ax.text(0, dram_means[0] + nvm_means[0] + 5, f'n={len(high_acc_good["dram"])}', ha='center', fontsize=9)
    ax.text(1, dram_means[1] + nvm_means[1] + 5, f'n={len(high_acc_bad["dram"])}', ha='center', fontsize=9)

    ax.set_ylabel('Mean Accesses per Interval')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()

    fig.suptitle('Liblinear-kddb: Access Distribution During Active Memory Periods\n(Intervals with total accesses >= median)',
                 fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()
    print(f"Saved: {outpath}")


def plot_stacked_area(dram_acc, nvm_acc, totals, modes, outpath, skip=100):
    """Stacked area chart over time."""
    dram = np.array(dram_acc[skip:])
    nvm = np.array(nvm_acc[skip:])
    t = np.array(totals[skip:])
    m = modes[skip:]
    x = np.arange(len(dram))

    # Smooth for readability
    window = 20
    if len(dram) > window:
        dram_smooth = np.convolve(dram, np.ones(window)/window, mode='valid')
        nvm_smooth = np.convolve(nvm, np.ones(window)/window, mode='valid')
        x_smooth = np.arange(len(dram_smooth))
    else:
        dram_smooth = dram
        nvm_smooth = nvm
        x_smooth = x

    fig, ax = plt.subplots(figsize=(14, 5))

    ax.fill_between(x_smooth, 0, dram_smooth, alpha=0.7, color='#6C8EBF', label='DRAM Accesses')
    ax.fill_between(x_smooth, dram_smooth, dram_smooth + nvm_smooth, alpha=0.7, color='#B85450', label='NVM Accesses')

    # Shade RECN regions
    recn_starts = []
    recn_ends = []
    in_recn = False
    for i, mode in enumerate(m):
        if mode == "recn" and not in_recn:
            recn_starts.append(i)
            in_recn = True
        elif mode == "hist" and in_recn:
            recn_ends.append(i)
            in_recn = False
    if in_recn:
        recn_ends.append(len(m))

    for i, (s, e) in enumerate(zip(recn_starts, recn_ends)):
        ax.axvspan(s, e, alpha=0.15, color='orange',
                   label='RECN mode' if i == 0 else None)

    ax.set_ylabel('Accesses per Interval (smoothed)')
    ax.set_xlabel('Interval')
    ax.legend(loc='upper right')

    fig.suptitle('Liblinear-kddb: DRAM vs NVM Accesses Over Time\n(20-interval moving average)',
                 fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()
    print(f"Saved: {outpath}")


if __name__ == '__main__':
    filepath = f"{BASE}/liblinear_kddb_and_pr_twitter/liblinear_kddb_1-8_cba_on_run1.txt"
    if not os.path.exists(filepath):
        filepath = f"{BASE}/_old_2026-04-28_cba_with_dram_frac/liblinear_kddb/liblinear_kddb_1-8_cba_on_run1.txt"

    dram_acc, nvm_acc, totals, modes = extract_data(filepath)

    # Skip startup
    start = 100
    dram_acc_trimmed = dram_acc[start:]
    nvm_acc_trimmed = nvm_acc[start:]
    totals_trimmed = totals[start:]

    plot_stacked_bars(dram_acc_trimmed, nvm_acc_trimmed, totals_trimmed,
                      os.path.join(BASE, 'placement_quality_bars.png'))

    plot_stacked_area(dram_acc, nvm_acc, totals, modes,
                      os.path.join(BASE, 'placement_quality_area.png'),
                      skip=100)
