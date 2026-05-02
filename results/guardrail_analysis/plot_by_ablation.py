#!/usr/bin/env python3
"""Plot guardrail violations per workload for a specific ablation vs baseline."""
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

METRICS = {
    'mig_eff': 'Migration Effectiveness Violations',
    'hotness_score': 'Hotness Score Boundary Violations',
    'dram_access_fraction': 'DRAM Access Fraction Violations',
}

HATCH = "/"
BASELINE_COLOR = "#C8C8C8"
BASELINE_EDGE = "#808080"
ABLATION_COLOR = "#DAE8FC"
ABLATION_EDGE = "#6C8EBF"


def extract_violations(filepath):
    vals = {}
    with open(filepath, 'r') as f:
        for line in f:
            m = re.search(r'mig_eff.*violations:\[(\d+)\]', line)
            if m:
                vals['mig_eff'] = int(m.group(1))
            m = re.search(r'hotness_score.*violations:\[(\d+)\]', line)
            if m:
                vals['hotness_score'] = int(m.group(1))
            m = re.search(r'dram_access_fraction.*violations:\[(\d+)\]', line)
            if m:
                vals['dram_access_fraction'] = int(m.group(1))
    return vals


def collect_results(results_dir):
    results = {}
    for dirpath, dirnames, filenames in os.walk(results_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith('_old')]
        for fname in filenames:
            if not fname.endswith('.txt'):
                continue
            filepath = os.path.join(dirpath, fname)
            vals = extract_violations(filepath)
            if not vals:
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
                        results[key] = {m: [] for m in METRICS}
                    for m in METRICS:
                        if m in vals:
                            results[key][m].append(vals[m])
                    break
    return results


def plot_ablation(results, results_dir, ablation_config, ablation_label):
    """Plot baseline vs ablation for each workload on the same graph per metric."""
    for metric, metric_label in METRICS.items():
        fig, ax = plt.subplots(figsize=(max(10, len(WORKLOADS) * 2.5), 5))

        labels = []
        baseline_vals = []
        ablation_vals = []
        has_data = False

        for wl_key, wl_label in WORKLOADS:
            baseline_key = (wl_key, "1-8", "cba_on")
            ablation_key = (wl_key, "1-8", ablation_config)

            bv = np.mean(results[baseline_key][metric]) if baseline_key in results and results[baseline_key][metric] else 0
            av = np.mean(results[ablation_key][metric]) if ablation_key in results and results[ablation_key][metric] else 0

            if bv > 0 or av > 0:
                has_data = True

            labels.append(wl_label)
            baseline_vals.append(bv)
            ablation_vals.append(av)

        if not has_data:
            plt.close()
            continue

        x = np.arange(len(labels))
        width = 0.35

        ax.bar(x - width/2, baseline_vals, width,
               color=BASELINE_COLOR, edgecolor=BASELINE_EDGE,
               hatch=HATCH, linewidth=1.2, label='Baseline')
        ax.bar(x + width/2, ablation_vals, width,
               color=ABLATION_COLOR, edgecolor=ABLATION_EDGE,
               hatch=HATCH, linewidth=1.2, label=ablation_label)

        ax.set_ylabel('Violation Count')
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=9)
        ax.legend()

        fig.suptitle(f'{metric_label}: Baseline vs {ablation_label}',
                     fontsize=13, fontweight='bold')
        plt.tight_layout()
        outpath = os.path.join(results_dir, f'{metric}_ablation_{ablation_config}.png')
        plt.savefig(outpath, dpi=150)
        plt.close()
        print(f"Saved: {outpath}")


ABLATIONS = {
    "cba_off": "CBA Off",
    "invert_sort": "Inverted Sort",
    "hcd_off": "HCD Off",
    "high_sample_period": "High Sample Period",
}


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <results_directory> [ablation]")
        print(f"  ablation: {', '.join(ABLATIONS.keys())} (default: all)")
        sys.exit(1)

    results_dir = sys.argv[1]
    if not os.path.isdir(results_dir):
        print(f"Error: {results_dir} is not a directory")
        sys.exit(1)

    results = collect_results(results_dir)
    if not results:
        print(f"No results found in {results_dir}")
        sys.exit(1)

    if len(sys.argv) >= 3:
        ablation = sys.argv[2]
        if ablation not in ABLATIONS:
            print(f"Unknown ablation: {ablation}")
            print(f"Options: {', '.join(ABLATIONS.keys())}")
            sys.exit(1)
        plot_ablation(results, results_dir, ablation, ABLATIONS[ablation])
    else:
        for config, label in ABLATIONS.items():
            plot_ablation(results, results_dir, config, label)
