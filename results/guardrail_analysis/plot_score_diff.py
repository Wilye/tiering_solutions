#!/usr/bin/env python3
"""Plot histogram of score differences between promoted and demoted pages for CBA on vs off."""
import os
import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

BASE = "/users/shelby/tiering_solutions/results/guardrail_analysis"


def extract_score_diffs(filepath):
    promote_scores = []
    demote_scores = []
    with open(filepath) as f:
        for line in f:
            m = re.search(r'Promoting at \d+: 0x\w+ score: ([\d.]+)', line)
            if m:
                promote_scores.append(float(m.group(1)))
            m = re.search(r'Demoting at \d+: 0x\w+ score: ([\d.]+)', line)
            if m:
                demote_scores.append(float(m.group(1)))

    pairs = min(len(promote_scores), len(demote_scores))
    diffs = [promote_scores[i] - demote_scores[i] for i in range(pairs)]
    return diffs


if __name__ == '__main__':
    # Use the old 04-13 runs which have the Promoting/Demoting log lines
    cba_on_path = None
    cba_off_path = None

    # Check multiple locations for files with Promoting/Demoting lines
    candidates = [
        ("_old_2026-04-13/silo_tpcc", "silo_tpcc_1-8_cba_on_run1.txt", "silo_tpcc_1-8_cba_off_run1.txt"),
        ("_old_2026-04-01/silo_tpcc", "silo_tpcc_1-8_cba_on_run1.txt", "silo_tpcc_1-8_cba_off_run1.txt"),
        ("silo_tpcc_and_pr_g25", "silo_tpcc_1-8_cba_on_run1.txt", "silo_tpcc_1-8_cba_off_run1.txt"),
    ]

    for subdir, on_file, off_file in candidates:
        on_path = os.path.join(BASE, subdir, on_file)
        off_path = os.path.join(BASE, subdir, off_file)
        if os.path.exists(on_path) and os.path.exists(off_path):
            # Check if they have Promoting lines
            with open(on_path) as f:
                if "Promoting at" in f.read():
                    cba_on_path = on_path
                    cba_off_path = off_path
                    break

    if not cba_on_path:
        print("Could not find result files with Promoting/Demoting log lines")
        exit(1)

    print(f"Using: {cba_on_path}")
    print(f"Using: {cba_off_path}")

    diffs_on = extract_score_diffs(cba_on_path)
    diffs_off = extract_score_diffs(cba_off_path)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5), sharey=True)

    # CBA On
    bins = np.linspace(0, 10, 50)
    ax1.hist([d for d in diffs_on if d <= 10], bins=bins, color='#C8C8C8', edgecolor='#808080', alpha=0.8)
    ax1.set_xlabel('Score Difference (Promoted - Demoted)')
    ax1.set_ylabel('Number of Migrations')
    ax1.set_title(f'CBA On ({len(diffs_on):,} swaps)')
    ax1.axvline(x=1.0, color='#B85450', linestyle='--', linewidth=1.5, label='Score diff = 1.0')
    lateral_on = sum(1 for d in diffs_on if d < 1.0)
    ax1.text(0.95, 0.95, f'{100*lateral_on/len(diffs_on):.1f}% < 1.0',
             transform=ax1.transAxes, ha='right', va='top', fontsize=10,
             bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    ax1.legend(fontsize=8)

    # CBA Off
    ax2.hist([d for d in diffs_off if d <= 10], bins=bins, color='#DAE8FC', edgecolor='#6C8EBF', alpha=0.8)
    ax2.set_xlabel('Score Difference (Promoted - Demoted)')
    ax2.set_title(f'CBA Off ({len(diffs_off):,} swaps)')
    ax2.axvline(x=1.0, color='#B85450', linestyle='--', linewidth=1.5, label='Score diff = 1.0')
    lateral_off = sum(1 for d in diffs_off if d < 1.0)
    ax2.text(0.95, 0.95, f'{100*lateral_off/len(diffs_off):.1f}% < 1.0',
             transform=ax2.transAxes, ha='right', va='top', fontsize=10,
             bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    ax2.legend(fontsize=8)

    fig.suptitle('Migration Score Differences: CBA On vs CBA Off (Silo-TPCC)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    outpath = os.path.join(BASE, 'score_diff_histogram.png')
    plt.savefig(outpath, dpi=150)
    plt.close()
    print(f"Saved: {outpath}")
    print(f"\nCBA On:  {len(diffs_on):,} swaps, {lateral_on:,} lateral ({100*lateral_on/len(diffs_on):.1f}%)")
    print(f"CBA Off: {len(diffs_off):,} swaps, {lateral_off:,} lateral ({100*lateral_off/len(diffs_off):.1f}%)")
