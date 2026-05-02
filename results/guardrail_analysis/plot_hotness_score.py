#!/usr/bin/env python3
"""Plot hotness score (boundary) guardrail violations."""
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

HATCH = "/"

WORKLOAD_COLORS = {
    "xsbench":          ("#D5E8D4", "#82B366"),
    "gapbs_bc_twitter": ("#DAE8FC", "#6C8EBF"),
    "silo_tpcc":        ("#FFE6CC", "#D79B00"),
    "liblinear_kddb":   ("#E1D5E7", "#9673A6"),
    "gapbs_pr_twitter": ("#F8CECC", "#B85450"),
}


def extract_violations(filepath):
    val = None
    with open(filepath, 'r') as f:
        for line in f:
            m = re.search(r'hotness_score.*violations:\[(\d+)\]', line)
            if m:
                val = int(m.group(1))
    return val


def collect_results(results_dir):
    results = {}
    for dirpath, dirnames, filenames in os.walk(results_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith('_old')]
        for fname in filenames:
            if not fname.endswith('.txt'):
                continue
            filepath = os.path.join(dirpath, fname)
            val = extract_violations(filepath)
            if val is None:
                continue
            for wl_key, _ in WORKLOADS:
                if fname.startswith(wl_key + "_"):
                    remainder = fname[len(wl_key) + 1:]
                    ratio_match = re.match(r'(\d+-\d+)_(.*)', remainder)
                    if not ratio_match:
                        break
                    ratio = ratio_match.group(1)
                    rest = ratio_match.group(2)
                    config_match = re.match(r'(.+)_run\d+\.txt$', rest)
                    if not config_match:
                        break
                    config = config_match.group(1)
                    if config == "normal":
                        continue
                    key = (wl_key, ratio, config)
                    if key not in results:
                        results[key] = []
                    results[key].append(val)
                    break
    return results


def get_configs(results):
    configs = sorted(set(c for (_, _, c) in results))
    if "cba_on" in configs:
        configs.remove("cba_on")
        configs.insert(0, "cba_on")
    return configs


def plot_workload(results, results_dir, workload, workload_label):
    configs = get_configs(results)
    ratios = sorted(set(r for (w, r, c) in results if w == workload))
    if not ratios:
        return

    wl_color, wl_edge = WORKLOAD_COLORS.get(workload, ("#D5E8D4", "#82B366"))
    fig, ax = plt.subplots(figsize=(max(8, len(configs) * 2), 5))

    labels = []
    means = []
    colors = []
    edge_colors = []
    for ratio in ratios:
        for config in configs:
            key = (workload, ratio, config)
            if key in results:
                config_label = ("Baseline" if config == "cba_on" else config.replace('_', ' ').title())
                labels.append(config_label if len(ratios) == 1 else f"{ratio.replace('-', ':')}\n{config_label}")
                means.append(np.mean(results[key]))
                if config == "cba_on":
                    colors.append("#C8C8C8")
                    edge_colors.append("#808080")
                else:
                    colors.append(wl_color)
                    edge_colors.append(wl_edge)

    if not labels:
        plt.close()
        return

    x = np.arange(len(labels))
    for i in range(len(labels)):
        ax.bar(x[i], means[i], 0.6, color=colors[i], edgecolor=edge_colors[i], hatch=HATCH, linewidth=1.2)
    ax.set_ylabel('Violation Count')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    fig.suptitle(f'{workload_label} — Hotness Score Boundary Violations', fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, f'hotness_score_{workload}.png'), dpi=150)
    plt.close()


def plot_summary(results, results_dir):
    configs = get_configs(results)
    fig, ax = plt.subplots(figsize=(max(10, len(WORKLOADS) * len(configs) * 1.2), 5))

    labels = []
    means = []
    colors = []
    edge_colors = []

    for workload, wl_label in WORKLOADS:
        for config in configs:
            key = (workload, "1-8", config)
            if key in results:
                config_label = ("Baseline" if config == "cba_on" else config.replace('_', ' ').title())
                labels.append(f"{wl_label}\n{config_label}")
                means.append(np.mean(results[key]))
                if config == "cba_on":
                    colors.append("#C8C8C8")
                    edge_colors.append("#808080")
                    continue
                c, ec = WORKLOAD_COLORS.get(workload, ("#D5E8D4", "#82B366"))
                colors.append(c)
                edge_colors.append(ec)

    if not labels:
        return

    x = np.arange(len(labels))
    for i in range(len(labels)):
        ax.bar(x[i], means[i], 0.6, color=colors[i], edgecolor=edge_colors[i], hatch=HATCH, linewidth=1.2)

    ax.set_ylabel('Violation Count')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7)
    fig.suptitle('Hotness Score Boundary Violations (1:8 Ratio)', fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, 'hotness_score_summary.png'), dpi=150)
    plt.close()


def print_summary(results):
    configs = get_configs(results)
    print(f"\n{'Workload':<20} {'Ratio':<8} {'Config':<20} {'Violations (mean +/- std)':<28}")
    print("-" * 76)
    for workload, wl_label in WORKLOADS:
        ratios = sorted(set(r for (w, r, c) in results if w == workload))
        for ratio in ratios:
            for config in configs:
                key = (workload, ratio, config)
                if key not in results:
                    continue
                vals = results[key]
                print(f"{wl_label:<20} {ratio:<8} {config:<20} {np.mean(vals):.1f} +/- {np.std(vals):.1f} (n={len(vals)})")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <results_directory>")
        sys.exit(1)
    results_dir = sys.argv[1]
    if not os.path.isdir(results_dir):
        print(f"Error: {results_dir} is not a directory")
        sys.exit(1)
    results = collect_results(results_dir)
    if not results:
        print(f"No results found in {results_dir}")
        sys.exit(1)
    plot_summary(results, results_dir)
    for workload, label in WORKLOADS:
        plot_workload(results, results_dir, workload, label)
    print_summary(results)
