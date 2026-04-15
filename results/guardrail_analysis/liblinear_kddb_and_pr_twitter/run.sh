#!/bin/bash

RESULTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="/users/shelby/tiering_solutions/src"
NUM_RUNS=3
TIMEOUT=1800  # 30 minutes

# Liblinear kddb config (1:8)
LIBLINEAR_BIN="/users/shelby/workloads/liblinear-2.47/train"
LIBLINEAR_ARGS="-s 6 -m 16 /users/shelby/workloads/liblinear-2.47/kddb"
LIBLINEAR_DRAMSIZE=2499805184   # 2.33 GiB
LIBLINEAR_NVMSIZE=20034093056   # 18.66 GiB

# GapBS PageRank twitter config (1:8)
PR_BIN="/users/shelby/workloads/gapbs/pr"
PR_ARGS="-n 16 -f /users/shelby/workloads/gapbs/benchmark/graphs/twitter.sg"
PR_DRAMSIZE=1470103552      # 1.37 GiB
PR_NVMSIZE=68719476736      # 64 GiB

run_workload() {
    local name=$1
    local bin=$2
    local args=$3
    local dramsize=$4
    local nvmsize=$5
    local cba_label=$6
    local run_num=$7
    local extra_env=$8

    local outfile="${RESULTS_DIR}/${name}_${cba_label}_run${run_num}.txt"
    echo "=== Running ${name} ${cba_label} run ${run_num} ==="
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

# --- CBA ON ---
echo "Building with CBA ON (default)..."
cd ${SRC_DIR}
make clean && make
echo ""

for i in $(seq 1 ${NUM_RUNS}); do
    run_workload "liblinear_kddb_1-8" "${LIBLINEAR_BIN}" "${LIBLINEAR_ARGS}" \
        ${LIBLINEAR_DRAMSIZE} ${LIBLINEAR_NVMSIZE} "cba_on" ${i}
done

for i in $(seq 1 ${NUM_RUNS}); do
    run_workload "gapbs_pr_twitter_1-8" "${PR_BIN}" "${PR_ARGS}" \
        ${PR_DRAMSIZE} ${PR_NVMSIZE} "cba_on" ${i} \
        "OMP_NUM_THREADS=16 MIN_INTERPOSE_MEM_SIZE=134217728"
done

# --- CBA OFF ---
echo "Building with CBA OFF..."
cd ${SRC_DIR}
make no-cba
echo ""

for i in $(seq 1 ${NUM_RUNS}); do
    run_workload "liblinear_kddb_1-8" "${LIBLINEAR_BIN}" "${LIBLINEAR_ARGS}" \
        ${LIBLINEAR_DRAMSIZE} ${LIBLINEAR_NVMSIZE} "cba_off" ${i}
done

for i in $(seq 1 ${NUM_RUNS}); do
    run_workload "gapbs_pr_twitter_1-8" "${PR_BIN}" "${PR_ARGS}" \
        ${PR_DRAMSIZE} ${PR_NVMSIZE} "cba_off" ${i} \
        "OMP_NUM_THREADS=16 MIN_INTERPOSE_MEM_SIZE=134217728"
done

# --- Rebuild default ---
echo "Rebuilding default (CBA ON)..."
cd ${SRC_DIR}
make clean && make

echo ""
echo "All experiments complete. Results in: ${RESULTS_DIR}"
