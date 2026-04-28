#!/usr/bin/env python3
import os
import re
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

WORKLOADS = [
    ("xsbench",          "XSBench"),
    ("gapbs_bc_twitter", "GapBS-BC (Twitter)"),
    ("silo_tpcc",        "Silo-TPCC"),
    ("liblinear_kddb",   "Liblinear-kddb"),
    ("gapbs_pr_twitter", "GapBS-PR (Twitter)"),
]

COLOR = "#D5E8D4"
EDGE_COLOR = "#82B366"
HATCH = "/"
MARKER = "o"


def extract_violations(filepath):
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


def collect_results(results_dir):
    results = {}

    for dirpath, dirnames, filenames in os.walk(results_dir):
        # Skip _old directories
        dirnames[:] = [d for d in dirnames if not d.startswith('_old')]
        for fname in filenames:
            if not fname.endswith('.txt'):
                continue
            filepath = os.path.join(dirpath, fname)
            mig_eff, hotness_score = extract_violations(filepath)
            if mig_eff is None and hotness_score is None:
                continue

            # Parse filename: {workload}_{ratio}_{config}_run{n}.txt
            # e.g. xsbench_1-8_cba_on_run1.txt, xsbench_1-8_normal_run1.txt
            for wl_key, _ in WORKLOADS:
                if fname.startswith(wl_key + "_"):
                    remainder = fname[len(wl_key) + 1:]  # e.g. "1-8_cba_on_run1.txt"
                    # Extract ratio
                    ratio_match = re.match(r'(\d+-\d+)_(.*)', remainder)
                    if not ratio_match:
                        break
                    ratio = ratio_match.group(1)
                    rest = ratio_match.group(2)  # e.g. "cba_on_run1.txt" or "normal_run1.txt"
                    # Extract config (everything before _runN.txt)
                    config_match = re.match(r'(.+)_run\d+\.txt$', rest)
                    if not config_match:
                        break
                    config = config_match.group(1)

                    key = (wl_key, ratio, config)
                    if key not in results:
                        results[key] = {'mig_eff': [], 'hotness_score': []}
                    if mig_eff is not None:
                        results[key]['mig_eff'].append(mig_eff)
                    if hotness_score is not None:
                        results[key]['hotness_score'].append(hotness_score)
                    break

    return results


def get_configs(results):
    configs = set()
    for (_, _, config) in results:
        configs.add(config)
    return sorted(configs)


def plot_workload(results, results_dir, workload, workload_label):
    configs = get_configs(results)
    ratios = set()
    for (wl, ratio, config) in results:
        if wl == workload:
            ratios.add(ratio)
    ratios = sorted(ratios)

    if not ratios:
        return

    fig, ax = plt.subplots(figsize=(max(8, len(configs) * 2), 5))

    labels = []
    vals_list = []

    for ratio in ratios:
        for config in configs:
            key = (workload, ratio, config)
            if key in results and results[key]['mig_eff']:
                config_label = config.replace('_', ' ').title()
                if len(ratios) > 1:
                    labels.append(f"{ratio.replace('-', ':')}\n{config_label}")
                else:
                    labels.append(config_label)
                vals_list.append(results[key]['mig_eff'])

    if not labels:
        plt.close()
        return

    x = np.arange(len(labels))
    for i in range(len(labels)):
        vals = vals_list[i]
        ax.bar(x[i], np.mean(vals), 0.6,
               color=COLOR, edgecolor=EDGE_COLOR,
               hatch=HATCH, linewidth=1.2)
        ax.scatter([i] * len(vals), vals,
                   color=EDGE_COLOR, marker=MARKER,
                   zorder=5, s=20, alpha=0.7)

    ax.set_ylabel('Violation Count')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)

    fig.suptitle(f'{workload_label} — Migration Effectiveness Violations',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, f'violations_{workload}.png'), dpi=150)
    plt.close()


WORKLOAD_COLORS = {
    "xsbench":          ("#D5E8D4", "#82B366"),  # green
    "gapbs_bc_twitter": ("#DAE8FC", "#6C8EBF"),  # blue
    "silo_tpcc":        ("#FFE6CC", "#D79B00"),  # orange
    "liblinear_kddb":   ("#E1D5E7", "#9673A6"),  # purple
    "gapbs_pr_twitter": ("#F8CECC", "#B85450"),  # red
}


def plot_summary(results, results_dir):
    configs = get_configs(results)

    fig, ax = plt.subplots(figsize=(max(10, len(WORKLOADS) * len(configs) * 1.2), 5))

    labels = []
    vals_list = []
    colors = []
    edge_colors = []

    for workload, wl_label in WORKLOADS:
        for config in configs:
            key = (workload, "1-8", config)
            if key in results and results[key]['mig_eff']:
                config_label = config.replace('_', ' ').title()
                labels.append(f"{wl_label}\n{config_label}")
                vals_list.append(results[key]['mig_eff'])
                c, ec = WORKLOAD_COLORS.get(workload, (COLOR, EDGE_COLOR))
                colors.append(c)
                edge_colors.append(ec)

    if not labels:
        print("No mig_eff data for summary plot")
        return

    x = np.arange(len(labels))
    for i in range(len(labels)):
        vals = vals_list[i]
        ax.bar(x[i], np.mean(vals), 0.6,
               color=colors[i], edgecolor=edge_colors[i],
               hatch=HATCH, linewidth=1.2)
        ax.scatter([i] * len(vals), vals,
                   color=edge_colors[i], marker=MARKER,
                   zorder=5, s=20, alpha=0.7)

    ax.set_ylabel('Violation Count')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7)

    fig.suptitle('ARMS Migration Effectiveness Violations (1:8 Ratio)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, 'violations_summary.png'), dpi=150)
    plt.close()


def print_summary(results):
    configs = get_configs(results)
    print(f"\n{'Workload':<20} {'Ratio':<8} {'Config':<20} {'Mig Eff (mean +/- std)':<28} {'Hotness (mean +/- std)':<28}")
    print("-" * 104)
    for workload, wl_label in WORKLOADS:
        ratios = sorted(set(r for (w, r, c) in results if w == workload))
        for ratio in ratios:
            for config in configs:
                key = (workload, ratio, config)
                if key not in results:
                    continue
                mig_vals = results[key]['mig_eff']
                hot_vals = results[key]['hotness_score']
                mig_str = f"{np.mean(mig_vals):.1f} +/- {np.std(mig_vals):.1f} (n={len(mig_vals)})" if mig_vals else "N/A"
                hot_str = f"{np.mean(hot_vals):.1f} +/- {np.std(hot_vals):.1f} (n={len(hot_vals)})" if hot_vals else "N/A"
                print(f"{wl_label:<20} {ratio:<8} {config:<20} {mig_str:<28} {hot_str:<28}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <results_directory>")
        print(f"  e.g. {sys.argv[0]} _old_2026-04-22")
        sys.exit(1)

    results_dir = sys.argv[1]
    if not os.path.isdir(results_dir):
        print(f"Error: {results_dir} is not a directory")
        sys.exit(1)

    results = collect_results(results_dir)
    if not results:
        print(f"No result files found in {results_dir}")
        sys.exit(1)

    plot_summary(results, results_dir)
    for workload, label in WORKLOADS:
        plot_workload(results, results_dir, workload, label)
    print_summary(results)
