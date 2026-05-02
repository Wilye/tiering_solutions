#!/usr/bin/env python3
"""Plot DRAM access fraction over time for comparing two runs."""
import os
import re
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def extract_timeseries(filepath):
    fractions = []
    ewmas = []
    migrations = []
    violations = []  # interval indices where violations occurred
    recn_starts = []
    recn_ends = []
    interval = 0

    mode = "hist"
    with open(filepath) as f:
        for line in f:
            if "Switching to RECN" in line:
                mode = "recn"
                recn_starts.append(interval)
            elif "Switching back to HIST" in line:
                mode = "hist"
                recn_ends.append(interval)

            m = re.search(r'DRAM_ACCESS_FRACTION: ([\d.]+) \(ewma=([\d.]+)', line)
            if m:
                fractions.append(float(m.group(1)))
                ewmas.append(float(m.group(2)))
                interval += 1

            m = re.search(r'Migrated (\d+) pages', line)
            if m:
                migrations.append(int(m.group(1)))

            if "DRAM_ACCESS_FRACTION VIOLATION" in line:
                violations.append(interval - 1)

    return fractions, ewmas, migrations, violations, recn_starts, recn_ends


def plot_comparison(file1, label1, file2, label2, title, outpath, skip_startup=0):
    frac1, ewma1, mig1, viol1, recn_starts1, recn_ends1 = extract_timeseries(file1)
    frac2, ewma2, mig2, viol2, recn_starts2, recn_ends2 = extract_timeseries(file2)

    # Skip startup intervals
    frac1 = frac1[skip_startup:]
    ewma1 = ewma1[skip_startup:]
    mig1 = mig1[skip_startup:]
    viol1 = [v - skip_startup for v in viol1 if v >= skip_startup]
    recn_starts1 = [r - skip_startup for r in recn_starts1 if r >= skip_startup]
    recn_ends1 = [r - skip_startup for r in recn_ends1 if r >= skip_startup]

    frac2 = frac2[skip_startup:]
    ewma2 = ewma2[skip_startup:]
    mig2 = mig2[skip_startup:]
    viol2 = [v - skip_startup for v in viol2 if v >= skip_startup]
    recn_starts2 = [r - skip_startup for r in recn_starts2 if r >= skip_startup]
    recn_ends2 = [r - skip_startup for r in recn_ends2 if r >= skip_startup]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    # Plot 1: DRAM fraction + migrations
    x1 = np.arange(len(frac1))
    ax1.plot(x1, frac1, alpha=0.3, color='#6C8EBF', linewidth=0.5, label='Fraction')
    ax1.plot(x1, ewma1, color='#6C8EBF', linewidth=1.5, label='EWMA')
    viol1_valid = [v for v in viol1 if v < len(frac1)]
    if viol1_valid:
        ax1.scatter(viol1_valid, [frac1[v] for v in viol1_valid], color='#B85450', marker='x', s=15, zorder=5, alpha=0.5, label='DRAM Frac Violation')
    for s, e in zip(recn_starts1, recn_ends1):
        ax1.axvspan(s, e, alpha=0.15, color='orange', label='RECN mode' if s == recn_starts1[0] else None)
    ax1.set_ylabel('DRAM Access Fraction', color='#6C8EBF')
    ax1.set_ylim(-0.05, 1.05)

    # Migrations on right y-axis
    ax1r = ax1.twinx()
    mig1_trimmed = mig1[:len(x1)]
    ax1r.bar(np.arange(len(mig1_trimmed)), mig1_trimmed, alpha=0.2, color='#82B366', width=1.0, label='Migrations')
    ax1r.set_ylabel('Migrations per interval', color='#82B366')
    ax1r.set_ylim(0, max(max(mig1_trimmed) if mig1_trimmed else 1, 1) * 1.5)

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines1r, labels1r = ax1r.get_legend_handles_labels()
    ax1.legend(lines1 + lines1r, labels1 + labels1r, loc='upper right', fontsize=8)
    ax1.set_title(label1, fontsize=11)

    # Plot 2: DRAM fraction + migrations
    x2 = np.arange(len(frac2))
    ax2.plot(x2, frac2, alpha=0.3, color='#B85450', linewidth=0.5, label='Fraction')
    ax2.plot(x2, ewma2, color='#B85450', linewidth=1.5, label='EWMA')
    viol2_valid = [v for v in viol2 if v < len(frac2)]
    if viol2_valid:
        ax2.scatter(viol2_valid, [frac2[v] for v in viol2_valid], color='#B85450', marker='x', s=15, zorder=5, alpha=0.5, label='DRAM Frac Violation')
    for s, e in zip(recn_starts2, recn_ends2):
        ax2.axvspan(s, e, alpha=0.15, color='orange', label='RECN mode' if s == recn_starts2[0] else None)
    ax2.set_ylabel('DRAM Access Fraction', color='#B85450')
    ax2.set_xlabel('Interval')
    ax2.set_ylim(-0.05, 1.05)

    ax2r = ax2.twinx()
    mig2_trimmed = mig2[:len(x2)]
    ax2r.bar(np.arange(len(mig2_trimmed)), mig2_trimmed, alpha=0.2, color='#82B366', width=1.0, label='Migrations')
    ax2r.set_ylabel('Migrations per interval', color='#82B366')
    ax2r.set_ylim(0, max(max(mig2_trimmed) if mig2_trimmed else 1, 1) * 1.5)

    lines2, labels2 = ax2.get_legend_handles_labels()
    lines2r, labels2r = ax2r.get_legend_handles_labels()
    ax2.legend(lines2 + lines2r, labels2 + labels2r, loc='upper right', fontsize=8)
    ax2.set_title(label2, fontsize=11)

    fig.suptitle(title, fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()
    print(f"Saved: {outpath}")


def plot_comparison_no_migrations(file1, label1, file2, label2, title, outpath, skip_startup=0):
    """Plot DRAM fraction comparison without migration overlay."""
    frac1, ewma1, mig1, viol1, recn_starts1, recn_ends1 = extract_timeseries(file1)
    frac2, ewma2, mig2, viol2, recn_starts2, recn_ends2 = extract_timeseries(file2)

    frac1 = frac1[skip_startup:]
    ewma1 = ewma1[skip_startup:]
    recn_starts1 = [r - skip_startup for r in recn_starts1 if r >= skip_startup]
    recn_ends1 = [r - skip_startup for r in recn_ends1 if r >= skip_startup]

    frac2 = frac2[skip_startup:]
    ewma2 = ewma2[skip_startup:]
    recn_starts2 = [r - skip_startup for r in recn_starts2 if r >= skip_startup]
    recn_ends2 = [r - skip_startup for r in recn_ends2 if r >= skip_startup]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    x1 = np.arange(len(frac1))
    ax1.plot(x1, frac1, alpha=0.3, color='#6C8EBF', linewidth=0.5, label='Fraction')
    ax1.plot(x1, ewma1, color='#6C8EBF', linewidth=1.5, label='EWMA')
    for s, e in zip(recn_starts1, recn_ends1):
        ax1.axvspan(s, e, alpha=0.15, color='orange', label='RECN mode' if s == recn_starts1[0] else None)
    ax1.set_ylabel('DRAM Access Fraction')
    ax1.set_title(label1, fontsize=11)
    ax1.set_ylim(-0.05, 1.05)
    ax1.legend(loc='upper right', fontsize=8)

    x2 = np.arange(len(frac2))
    ax2.plot(x2, frac2, alpha=0.3, color='#B85450', linewidth=0.5, label='Fraction')
    ax2.plot(x2, ewma2, color='#B85450', linewidth=1.5, label='EWMA')
    for s, e in zip(recn_starts2, recn_ends2):
        ax2.axvspan(s, e, alpha=0.15, color='orange', label='RECN mode' if s == recn_starts2[0] else None)
    ax2.set_ylabel('DRAM Access Fraction')
    ax2.set_xlabel('Interval')
    ax2.set_title(label2, fontsize=11)
    ax2.set_ylim(-0.05, 1.05)
    ax2.legend(loc='upper right', fontsize=8)

    fig.suptitle(title, fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()
    print(f"Saved: {outpath}")


if __name__ == '__main__':
    base = "/users/shelby/tiering_solutions/results/guardrail_analysis"

    # XSBench normal vs inverted sort — with migrations
    plot_comparison(
        f"{base}/xsbench_and_bc_twitter/xsbench_1-8_cba_on_run1.txt",
        "XSBench — Normal",
        f"{base}/xsbench_and_bc_twitter/xsbench_1-8_invert_sort_run1.txt",
        "XSBench — Inverted Sort (no CBA)",
        "XSBench: DRAM Access Fraction and Migrations Over Time",
        f"{base}/timeseries_xsbench_invert.png",
        skip_startup=50,
    )

    # Liblinear HCD on vs HCD off — overlaid on same graph
    frac1, ewma1, mig1, viol1, rs1, re1 = extract_timeseries(
        f"{base}/liblinear_kddb_and_pr_twitter/liblinear_kddb_1-8_cba_on_run1.txt")
    frac2, ewma2, mig2, viol2, rs2, re2 = extract_timeseries(
        f"{base}/liblinear_kddb_and_pr_twitter/liblinear_kddb_1-8_hcd_off_run1.txt")

    skip = 50
    ewma1 = ewma1[skip:]
    ewma2 = ewma2[skip:]
    rs1 = [r - skip for r in rs1 if r >= skip]
    re1 = [r - skip for r in re1 if r >= skip]

    n = min(len(ewma1), len(ewma2))
    x = np.arange(n)

    fig, ax = plt.subplots(figsize=(14, 5))

    ax.plot(x, ewma1[:n], color='#6C8EBF', linewidth=1.5, label='HCD On (EWMA)', zorder=3)
    ax.plot(x, ewma2[:n], color='#B85450', linewidth=1.5, label='HCD Off (EWMA)', zorder=3)

    for i, (s, e) in enumerate(zip(rs1, re1)):
        if s < n and e < n:
            ax.axvspan(s, e, alpha=0.15, color='orange',
                       label='RECN mode (HCD On)' if i == 0 else None)

    ax.set_ylabel('DRAM Access Fraction (EWMA)')
    ax.set_xlabel('Interval')
    ax.set_ylim(-0.05, 1.05)
    ax.legend(loc='upper right', fontsize=9)

    fig.suptitle('Liblinear: DRAM Access Fraction with HCD On vs Off',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    outpath = f"{base}/timeseries_liblinear_hcd.png"
    plt.savefig(outpath, dpi=150)
    plt.close()
    print(f"Saved: {outpath}")

    # Silo HCD on vs HCD off — overlaid on same graph
    frac1, ewma1, mig1, viol1, rs1, re1 = extract_timeseries(
        f"{base}/silo_tpcc_and_pr_g25/silo_tpcc_1-8_cba_on_run1.txt")
    frac2, ewma2, mig2, viol2, rs2, re2 = extract_timeseries(
        f"{base}/silo_tpcc_and_pr_g25/silo_tpcc_1-8_hcd_off_run1.txt")

    skip = 50
    ewma1 = ewma1[skip:]
    ewma2 = ewma2[skip:]
    rs1 = [r - skip for r in rs1 if r >= skip]
    re1 = [r - skip for r in re1 if r >= skip]

    n = min(len(ewma1), len(ewma2))
    x = np.arange(n)

    fig, ax = plt.subplots(figsize=(14, 5))

    ax.plot(x, ewma1[:n], color='#6C8EBF', linewidth=1.5, label='HCD On (EWMA)', zorder=3)
    ax.plot(x, ewma2[:n], color='#B85450', linewidth=1.5, label='HCD Off (EWMA)', zorder=3)

    for i, (s, e) in enumerate(zip(rs1, re1)):
        if s < n and e < n:
            ax.axvspan(s, e, alpha=0.15, color='orange',
                       label='RECN mode (HCD On)' if i == 0 else None)

    ax.set_ylabel('DRAM Access Fraction (EWMA)')
    ax.set_xlabel('Interval')
    ax.set_ylim(-0.05, 1.05)
    ax.legend(loc='upper right', fontsize=9)

    fig.suptitle('Silo-TPCC: DRAM Access Fraction with HCD On vs Off',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    outpath = f"{base}/timeseries_silo_hcd.png"
    plt.savefig(outpath, dpi=150)
    plt.close()
    print(f"Saved: {outpath}")
