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
    ("gapbs_bc_twitter",   "GapBS-BC"),
    ("silo_tpcc",          "Silo-TPCC"),
    ("gapbs_pr_g25",       "GapBS-PR (g25)"),
    ("liblinear_kddb",     "Liblinear-kddb"),
    ("gapbs_pr_twitter",   "GapBS-PR (twitter)"),
]

RATIOS = ["2-1", "1-1", "1-2", "1-4", "1-8", "1-16"]
CBA_MODES = ["cba_on", "cba_off"]

def extract_violations(filepath):
    """Extract mig_eff and hotness_score violation counts from a log file."""
    mig_eff = None
    hotness_score = None
    with open(filepath, 'r') as f:
        for line in f:
            m = re.search(r'mig_eff.*violations:\[(\d+)\]', line)
            if m:
                mig_eff = int(m.group(1))
            m = re.search(r'hotness_score.*violations:\[(\d+)\]', line)
            if m:
                hotness_score = int(m.group(1))
    return mig_eff, hotness_score

def collect_results():
    """Collect results from all subdirectories, keyed by (workload, ratio, cba_mode)."""
    results = {}
    for workload, _ in WORKLOADS:
        for ratio in RATIOS:
            for cba in CBA_MODES:
                prefix = f"{workload}_{ratio}_{cba}"
                mig_effs = []
                hotness_scores = []
                # Search in all subdirectories
                for dirpath, _, filenames in os.walk(RESULTS_DIR):
                    for run in range(1, 20):
                        fname = f"{prefix}_run{run}.txt"
                        if fname in filenames:
                            filepath = os.path.join(dirpath, fname)
                            me, hs = extract_violations(filepath)
                            if me is not None:
                                mig_effs.append(me)
                            if hs is not None:
                                hotness_scores.append(hs)
                if mig_effs or hotness_scores:
                    results[(workload, ratio, cba)] = {
                        'mig_eff': mig_effs,
                        'hotness_score': hotness_scores,
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
                configs.append((f"{label}\n{cba_label}", key))

    if not configs:
        print("No 1:8 data found, skipping 1:8 comparison plot.")
        return

    labels = [c[0] for c in configs]
    n = len(labels)
    x = np.arange(n)
    width = 0.35

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(max(14, n * 1.5), 5))

    # Colors: alternate blue/orange for CBA on/off
    colors = ['#4c72b0' if 'On' in l else '#dd8452' for l in labels]

    for ax, metric, title in [
        (ax1, 'mig_eff', 'Migration Effectiveness Violations'),
        (ax2, 'hotness_score', 'Hotness Score Violations'),
    ]:
        means = []
        stds = []
        all_vals = []
        for _, key in configs:
            vals = results[key][metric] if key in results and results[key][metric] else []
            means.append(np.mean(vals) if vals else 0)
            stds.append(np.std(vals) if len(vals) > 1 else 0)
            all_vals.append(vals)

        ax.bar(x, means, width, yerr=stds, capsize=5, color=colors)
        ax.set_ylabel('Violation Count')
        ax.set_title(title)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=7)

        for i, vals in enumerate(all_vals):
            ax.scatter([i] * len(vals), vals, color='black', zorder=5, s=20, alpha=0.7)

    fig.suptitle('ARMS Guardrail Violations (1:8 Ratio)', fontsize=13, fontweight='bold')
    plt.tight_layout()

    outpath = os.path.join(RESULTS_DIR, 'violations_plot.png')
    plt.savefig(outpath, dpi=150)
    print(f"Plot saved to: {outpath}")

def plot_by_workload(results, workload, workload_label):
    """Plot violations across ratios for a single workload."""
    ratios_with_data = [r for r in RATIOS
                        if (workload, r, 'cba_on') in results
                        or (workload, r, 'cba_off') in results]

    if not ratios_with_data:
        print(f"No data for {workload_label}, skipping ratio plot.")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    x = np.arange(len(ratios_with_data))
    width = 0.35

    for ax, metric, title in [
        (ax1, 'mig_eff', 'Migration Effectiveness Violations'),
        (ax2, 'hotness_score', 'Hotness Score Violations'),
    ]:
        for j, (cba, color, label) in enumerate([
            ('cba_on', '#4c72b0', 'CBA On'),
            ('cba_off', '#dd8452', 'CBA Off'),
        ]):
            means = []
            stds = []
            all_vals = []
            for ratio in ratios_with_data:
                key = (workload, ratio, cba)
                if key in results and results[key][metric]:
                    vals = results[key][metric]
                    means.append(np.mean(vals))
                    stds.append(np.std(vals) if len(vals) > 1 else 0)
                    all_vals.append(vals)
                else:
                    means.append(0)
                    stds.append(0)
                    all_vals.append([])

            offset = -width/2 + j * width
            ax.bar(x + offset, means, width, yerr=stds, capsize=4,
                   color=color, label=label, alpha=0.8)

            for i, vals in enumerate(all_vals):
                if vals:
                    ax.scatter([x[i] + offset] * len(vals), vals,
                             color='black', zorder=5, s=15, alpha=0.6)

        ax.set_ylabel('Violation Count')
        ax.set_title(title)
        ax.set_xticks(x)
        ax.set_xticklabels([r.replace('-', ':') for r in ratios_with_data])
        ax.set_xlabel('DRAM:NVM Ratio')
        ax.legend()

    fig.suptitle(f'{workload_label} — Guardrail Violations Across Ratios',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()

    outpath = os.path.join(RESULTS_DIR, f'violations_{workload}.png')
    plt.savefig(outpath, dpi=150)
    print(f"Plot saved to: {outpath}")

def print_summary(results):
    print("\n=== Summary Table ===")
    print(f"{'Workload':<20} {'Ratio':<8} {'CBA':<8} "
          f"{'Mig Eff (mean +/- std)':<28} {'Hotness Score (mean +/- std)':<30}")
    print("-" * 94)
    for workload, wl_label in WORKLOADS:
        for ratio in RATIOS:
            for cba in CBA_MODES:
                key = (workload, ratio, cba)
                if key not in results:
                    continue
                r = results[key]
                me = r['mig_eff']
                hs = r['hotness_score']
                me_str = f"{np.mean(me):.1f} +/- {np.std(me):.1f} (n={len(me)})" if me else "N/A"
                hs_str = f"{np.mean(hs):.1f} +/- {np.std(hs):.1f} (n={len(hs)})" if hs else "N/A"
                print(f"{wl_label:<20} {ratio:<8} {cba:<8} {me_str:<28} {hs_str:<30}")

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
