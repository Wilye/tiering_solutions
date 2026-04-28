#!/bin/bash

RESULTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="/users/shelby/tiering_solutions/src"
NUM_RUNS=1
TIMEOUT=1800  # 30 minutes

SILO_BIN="/users/shelby/tiering_solutions/apps/silo/silo/out-perf.masstree/benchmarks/dbtest"
SILO_ARGS="--verbose --bench tpcc --num-threads 20 --scale-factor 100 --ops-per-worker 8000000 --numa-memory 85743345664"
SILO_DRAMSIZE=9299992576    # 8.66 GiB
SILO_NVMSIZE=83019956224    # 77.32 GiB (69.32 + 8 extra)

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

ABLATION=${1:-"cba"}

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
    for i in $(seq 1 ${NUM_RUNS}); do
        run_workload "silo_tpcc_1-8" "${SILO_BIN}" "${SILO_ARGS}" \
            ${SILO_DRAMSIZE} ${SILO_NVMSIZE} "${label}" ${i} \
            "OMP_NUM_THREADS=20"
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
