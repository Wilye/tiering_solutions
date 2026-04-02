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
    ("xsbench",          "XSBench"),
    ("gapbs_bc_twitter", "GapBS-BC (Twitter)"),
    ("silo_tpcc",        "Silo-TPCC"),
    ("liblinear_kddb",   "Liblinear-kddb"),
    ("gapbs_pr_twitter", "GapBS-PR (Twitter)"),
]

RATIOS = ["2-1", "1-1", "1-2", "1-4", "1-8", "1-16"]
CBA_MODES = ["cba_on", "cba_off"]

COLOR = "#D5E8D4"
EDGE_COLOR = "#82B366"
HATCH = "/"
MARKER = "o"


def extract_violations(filepath):
    mig_eff = None
    with open(filepath, 'r') as f:
        for line in f:
            m = re.search(r'mig_eff.*violations:\[(\d+)\]', line)
            if m:
                mig_eff = int(m.group(1))
    # finds the last match to the regex
    return mig_eff


def collect_results():
    results = {}
    for workload, _ in WORKLOADS:
        for ratio in RATIOS:
            for cba in CBA_MODES:
                prefix = f"{workload}_{ratio}_{cba}"
                vals = []
                for dirpath, _, filenames in os.walk(RESULTS_DIR):
                    for run in range(1, 20):
                        fname = f"{prefix}_run{run}.txt"
                        if fname in filenames:
                            v = extract_violations(os.path.join(dirpath, fname))
                            if v is not None:
                                vals.append(v)
                if vals:
                    results[(workload, ratio, cba)] = vals
    return results


def plot_1_8_comparison(results):
    labels = []
    vals_list = []

    for workload, wl_label in WORKLOADS:
        for cba in CBA_MODES:
            key = (workload, "1-8", cba)
            if key in results:
                if cba == "cba_on":
                    cba_label = "CBA On"
                else:
                    cba_label = "CBA Off"
                labels.append(f"{wl_label}\n{cba_label}")
                vals_list.append(results[key])

    if not labels:
        return

    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(max(10, len(labels) * 1.5), 5))

    for i in range(len(labels)):
        vals = vals_list[i]
        ax.bar(x[i], np.mean(vals), 0.35,
               color=COLOR, edgecolor=EDGE_COLOR,
               hatch=HATCH, linewidth=1.2)
        ax.scatter([i] * len(vals), vals,
                   color=EDGE_COLOR, marker=MARKER,
                   zorder=5, s=20, alpha=0.7)

    ax.set_ylabel('Violation Count')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7)
    fig.suptitle('ARMS Migration Effectiveness Violations (1:8 Ratio)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(RESULTS_DIR, 'violations_plot.png'), dpi=150)


def plot_by_workload(results, workload, workload_label):
    # xsbench and gapbs_bc only have 1:8 data
    if workload in ("xsbench", "gapbs_bc_twitter"):
        candidate_ratios = ["1-8"]
    else:
        candidate_ratios = RATIOS

    ratios = []
    for r in candidate_ratios:
        if (workload, r, 'cba_on') in results or (workload, r, 'cba_off') in results:
            ratios.append(r)

    if not ratios:
        return

    x = np.arange(len(ratios))
    width = 0.35
    fig, ax = plt.subplots(figsize=(max(7, len(ratios) * 2), 5))

    cba_configs = [('cba_on', 'CBA On'), ('cba_off', 'CBA Off')]
    for j in range(len(cba_configs)):
        cba, label = cba_configs[j]
        means = []
        all_vals = []
        for ratio in ratios:
            key = (workload, ratio, cba)
            if key in results:
                vals = results[key]
                means.append(np.mean(vals))
                all_vals.append(vals)
            else:
                means.append(0)
                all_vals.append([])

        offset = -width/2 + j * width
        ax.bar(x + offset, means, width,
               color=COLOR, edgecolor=EDGE_COLOR,
               hatch=HATCH, linewidth=1.2, label=label, alpha=0.8)

        for i in range(len(all_vals)):
            vals = all_vals[i]
            if vals:
                ax.scatter([x[i] + offset] * len(vals), vals,
                           color=EDGE_COLOR, marker=MARKER,
                           zorder=5, s=15, alpha=0.6)

    ax.set_ylabel('Violation Count')
    if len(ratios) > 1:
        ratio_labels = []
        for r in ratios:
            ratio_labels.append(r.replace('-', ':'))
        ax.set_xticks(x)
        ax.set_xticklabels(ratio_labels)
        ax.set_xlabel('DRAM:NVM Ratio')
    else:
        ax.set_xticks([])
    ax.legend()
    fig.suptitle(f'{workload_label} — ARMS Migration Effectiveness Violations (1:8 Ratio)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(RESULTS_DIR, f'violations_{workload}.png'), dpi=150)


def print_summary(results):
    print("\n=== Summary ===")
    print(f"{'Workload':<20} {'Ratio':<8} {'CBA':<8} {'Mig Eff (mean +/- std)':<28}")
    print("-" * 64)
    for workload, wl_label in WORKLOADS:
        for ratio in RATIOS:
            for cba in CBA_MODES:
                key = (workload, ratio, cba)
                if key not in results:
                    continue
                vals = results[key]
                mean = np.mean(vals)
                std = np.std(vals)
                print(f"{wl_label:<20} {ratio:<8} {cba:<8} "
                      f"{mean:.1f} +/- {std:.1f} (n={len(vals)})")


if __name__ == '__main__':
    results = collect_results()
    if not results:
        print("No result files found.")
        sys.exit(1)

    plot_1_8_comparison(results)
    for workload, label in WORKLOADS:
        plot_by_workload(results, workload, label)
    print_summary(results)
