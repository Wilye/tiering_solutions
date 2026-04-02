#!/usr/bin/env python3
import os
import re
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

RESULTS_DIR = os.path.dirname(os.path.abspath(__file__))

WORKLOADS = [
    ("xsbench",            "XSBench"),
    ("gapbs_bc_twitter",   "GapBS-BC (Twitter)"),
    ("silo_tpcc",          "Silo-TPCC"),
    ("liblinear_kddb",     "Liblinear-kddb")11,
    ("gapbs_pr_twitter",   "GapBS-PR (Twitter)"),
]

RATIOS = ["2-1", "1-1", "1-2", "1-4", "1-8", "1-16"]
CBA_MODES = ["cba_on", "cba_off"]

# Single color for all workloads (only one baseline: ARMS)
COLOR = "#D5E8D4"
EDGE_COLOR = "#82B366"
HATCH = "/"
MARKER = "o"

def extract_violations(filepath):
    """Extract mig_eff violation count from a log file."""
    mig_eff = None
    with open(filepath, 'r') as f:
        for line in f:
            m = re.search(r'mig_eff.*violations:\[(\d+)\]', line)
            if m:
                mig_eff = int(m.group(1))
    return mig_eff

def collect_results():
    """Collect results from all subdirectories, keyed by (workload, ratio, cba_mode)."""
    results = {}
    for workload, _ in WORKLOADS:
        for ratio in RATIOS:
            for cba in CBA_MODES:
                prefix = f"{workload}_{ratio}_{cba}"
                mig_effs = []
                # Search in all subdirectories
                for dirpath, _, filenames in os.walk(RESULTS_DIR):
                    for run in range(1, 20):
                        fname = f"{prefix}_run{run}.txt"
                        if fname in filenames:
                            filepath = os.path.join(dirpath, fname)
                            me = extract_violations(filepath)
                            if me is not None:
                                mig_effs.append(me)
                if mig_effs:
                    results[(workload, ratio, cba)] = {
                        'mig_eff': mig_effs,
                    }
    return results

def plot_1_8_comparison(results):
    """Bar chart comparing all workloads at 1:8 ratio, CBA on vs off."""
    configs = []
    for workload, label in WORKLOADS:
        for cba in CBA_MODES:
            key = (workload, "1-8", cba)
            if key in results:
                cba_label = "CBA On" if cba == "cba_on" else "CBA Off"
                configs.append((f"{label}\n{cba_label}", key, workload))

    if not configs:
        print("No 1:8 data found, skipping 1:8 comparison plot.")
        return

    labels = [c[0] for c in configs]
    n = len(labels)
    x = np.arange(n)
    width = 0.35

    fig, ax = plt.subplots(figsize=(max(10, n * 1.5), 5))

    means = []
    all_vals = []
    for _, key, _ in configs:
        vals = results[key]['mig_eff'] if key in results and results[key]['mig_eff'] else []
        means.append(np.mean(vals) if vals else 0)
        all_vals.append(vals)

    for i in range(n):
        ax.bar(x[i], means[i], width,
               color=COLOR, edgecolor=EDGE_COLOR,
               hatch=HATCH, linewidth=1.2)
    ax.set_ylabel('Violation Count')
    ax.set_title('Migration Effectiveness Violations')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7)

    for i, vals in enumerate(all_vals):
        ax.scatter([i] * len(vals), vals, color=EDGE_COLOR,
                   marker=MARKER, zorder=5, s=20, alpha=0.7)

    fig.suptitle('ARMS Migration Effectiveness Violations (1:8 Ratio)', fontsize=13, fontweight='bold')
    plt.tight_layout()

    outpath = os.path.join(RESULTS_DIR, 'violations_plot.png')
    plt.savefig(outpath, dpi=150)
    print(f"Plot saved to: {outpath}")

def plot_by_workload(results, workload, workload_label):
    """Plot mig_eff violations across ratios for a single workload."""
    # XSBench and GapBS-BC: only plot 1:8 ratio
    if workload in ("xsbench", "gapbs_bc_twitter"):
        candidate_ratios = ["1-8"]
    else:
        candidate_ratios = RATIOS

    ratios_with_data = [r for r in candidate_ratios
                        if (workload, r, 'cba_on') in results
                        or (workload, r, 'cba_off') in results]

    if not ratios_with_data:
        print(f"No data for {workload_label}, skipping ratio plot.")
        return

    fig, ax = plt.subplots(figsize=(max(7, len(ratios_with_data) * 2), 5))
    x = np.arange(len(ratios_with_data))
    width = 0.35

    for j, (cba, label) in enumerate([
        ('cba_on', 'CBA On'),
        ('cba_off', 'CBA Off'),
    ]):
        means = []
        all_vals = []
        for ratio in ratios_with_data:
            key = (workload, ratio, cba)
            if key in results and results[key]['mig_eff']:
                vals = results[key]['mig_eff']
                means.append(np.mean(vals))
                all_vals.append(vals)
            else:
                means.append(0)
                all_vals.append([])

        offset = -width/2 + j * width
        if cba == 'cba_on':
            ax.bar(x + offset, means, width,
                   color=COLOR, edgecolor=EDGE_COLOR,
                   hatch=HATCH, linewidth=1.2, label=label, alpha=0.8)
        else:
            ax.bar(x + offset, means, width,
                   color='white', edgecolor=EDGE_COLOR,
                   hatch=HATCH, linewidth=1.2, label=label, alpha=0.8)

        for i, vals in enumerate(all_vals):
            if vals:
                ax.scatter([x[i] + offset] * len(vals), vals,
                         color=EDGE_COLOR, marker=MARKER,
                         zorder=5, s=15, alpha=0.6)

    ax.set_ylabel('Violation Count')
    ax.set_title('Migration Effectiveness Violations')
    if len(ratios_with_data) > 1:
        ax.set_xticks(x)
        ax.set_xticklabels([r.replace('-', ':') for r in ratios_with_data])
        ax.set_xlabel('DRAM:NVM Ratio')
    else:
        ax.set_xticks([])
    ax.legend()

    fig.suptitle(f'{workload_label} — ARMS Migration Effectiveness Violations (1:8 Ratio)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()

    outpath = os.path.join(RESULTS_DIR, f'violations_{workload}.png')
    plt.savefig(outpath, dpi=150)
    print(f"Plot saved to: {outpath}")

def print_summary(results):
    print("\n=== Summary Table ===")
    print(f"{'Workload':<20} {'Ratio':<8} {'CBA':<8} "
          f"{'Mig Eff (mean +/- std)':<28}")
    print("-" * 64)
    for workload, wl_label in WORKLOADS:
        for ratio in RATIOS:
            for cba in CBA_MODES:
                key = (workload, ratio, cba)
                if key not in results:
                    continue
                r = results[key]
                me = r['mig_eff']
                me_str = f"{np.mean(me):.1f} +/- {np.std(me):.1f} (n={len(me)})" if me else "N/A"
                print(f"{wl_label:<20} {ratio:<8} {cba:<8} {me_str:<28}")

if __name__ == '__main__':
    results = collect_results()
    if not results:
        print("No result files found. Run experiments first.")
        sys.exit(1)

    # 1:8 comparison across all workloads
    plot_1_8_comparison(results)

    # Per-workload ratio plots (only if multiple ratios exist)
    for workload, label in WORKLOADS:
        plot_by_workload(results, workload, label)

    print_summary(results)
