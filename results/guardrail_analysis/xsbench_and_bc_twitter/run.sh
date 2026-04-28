#!/bin/bash

RESULTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="/users/shelby/tiering_solutions/src"
NUM_RUNS=1
TIMEOUT=1800  # 30 minutes

XSBENCH_BIN="/users/shelby/workloads/XSBench/openmp-threading/XSBench"
XSBENCH_ARGS="-g 130000 -p 20000000 -t 20"

GAPBS_BIN="/users/shelby/workloads/gapbs/bc"
GAPBS_ARGS="-n 16 -f /users/shelby/workloads/gapbs/benchmark/graphs/twitter.sg"
GAPBS_NVMSIZE=68719476736  # 64 GiB

# GiB to bytes (rounded down to 2 MiB page alignment)
gib_to_bytes() {
    python3 -c "
v = $1 * 1024 * 1024 * 1024
page = 2 * 1024 * 1024
v = int(v // page) * page
print(v)
"
}

run_workload() {
    local name=$1
    local bin=$2
    local args=$3
    local dramsize=$4
    local nvmsize=$5
    local label=$6
    local run_num=$7
    local extra_env=$8

    local outfile="${RESULTS_DIR}/${name}_${label}_run${run_num}.txt"
    echo "=== Running ${name} ${label} run ${run_num} ==="
    echo "  Output: ${outfile}"

    { time timeout ${TIMEOUT} sudo numactl -N0 env DRAMSIZE=${dramsize} NVMSIZE=${nvmsize} ${extra_env} \
        LD_PRELOAD=${SRC_DIR}/libarms.so \
        ${bin} ${args} ; } > "${outfile}" 2>&1

    local exit_code=$?
    if [ ${exit_code} -eq 124 ]; then
        echo "  TIMED OUT after ${TIMEOUT}s"
    else
        echo "  Done (exit code: ${exit_code})"
    fi
}

# XSBench ratios
XSBENCH_RATIOS="1-8"
declare -A XSBENCH_DRAM XSBENCH_NVM
XSBENCH_DRAM[2-1]=43.31;  XSBENCH_NVM[2-1]=21.66
XSBENCH_DRAM[1-1]=32.49;  XSBENCH_NVM[1-1]=32.49
XSBENCH_DRAM[1-2]=21.66;  XSBENCH_NVM[1-2]=43.31
XSBENCH_DRAM[1-4]=12.99;  XSBENCH_NVM[1-4]=51.98
XSBENCH_DRAM[1-8]=7.22;   XSBENCH_NVM[1-8]=62.00
XSBENCH_DRAM[1-16]=3.82;  XSBENCH_NVM[1-16]=61.15

# GapBS BC twitter ratios
GAPBS_RATIOS="1-8"
declare -A GAPBS_DRAM
GAPBS_DRAM[2-1]=8.72
GAPBS_DRAM[1-1]=6.54
GAPBS_DRAM[1-2]=4.36
GAPBS_DRAM[1-4]=2.62
GAPBS_DRAM[1-8]=1.45
GAPBS_DRAM[1-16]=0.77

# --- Ablation selection ---
ABLATION=${1:-"cba"}  # default: cba

usage() {
    echo "Usage: $0 <ablation>"
    echo "  cba          - CBA on vs CBA off"
    echo "  invert_sort  - Normal vs inverted sort (no CBA)"
    echo "  hcd          - HCD on vs HCD off"
    echo "  sample_period - Normal vs high sample period"
    exit 1
}

run_all_workloads() {
    local label=$1
    for ratio in ${XSBENCH_RATIOS}; do
        dram=$(gib_to_bytes ${XSBENCH_DRAM[$ratio]})
        nvm=$(gib_to_bytes ${XSBENCH_NVM[$ratio]})
        for i in $(seq 1 ${NUM_RUNS}); do
            run_workload "xsbench_${ratio}" "${XSBENCH_BIN}" "${XSBENCH_ARGS}" \
                ${dram} ${nvm} "${label}" ${i}
        done
    done

    for ratio in ${GAPBS_RATIOS}; do
        dram=$(gib_to_bytes ${GAPBS_DRAM[$ratio]})
        for i in $(seq 1 ${NUM_RUNS}); do
            run_workload "gapbs_bc_twitter_${ratio}" "${GAPBS_BIN}" "${GAPBS_ARGS}" \
                ${dram} ${GAPBS_NVMSIZE} "${label}" ${i} \
                "OMP_NUM_THREADS=20 MIN_INTERPOSE_MEM_SIZE=134217728"
        done
    done
}

case ${ABLATION} in
    cba)
        echo "=== Ablation: CBA on vs CBA off ==="
        cd ${SRC_DIR} && make clean && make
        run_all_workloads "cba_on"
        cd ${SRC_DIR} && make no-cba
        run_all_workloads "cba_off"
        ;;
    invert_sort)
        echo "=== Ablation: Normal vs Inverted Sort (no CBA) ==="
        cd ${SRC_DIR} && make clean && make
        run_all_workloads "normal"
        cd ${SRC_DIR} && make invert-sort-no-cba
        run_all_workloads "invert_sort"
        ;;
    hcd)
        echo "=== Ablation: HCD on vs HCD off ==="
        cd ${SRC_DIR} && make clean && make
        run_all_workloads "hcd_on"
        cd ${SRC_DIR} && make no-hcd
        run_all_workloads "hcd_off"
        ;;
    sample_period)
        echo "=== Ablation: Normal vs High Sample Period ==="
        cd ${SRC_DIR} && make clean && make
        run_all_workloads "normal_sample"
        cd ${SRC_DIR} && make high-sample-period
        run_all_workloads "high_sample_period"
        ;;
    *)
        usage
        ;;
esac

# --- Rebuild default ---
echo "Rebuilding default..."
cd ${SRC_DIR}
make clean && make

echo ""
echo "All experiments complete. Results in: ${RESULTS_DIR}"
